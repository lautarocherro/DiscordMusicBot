import os
import asyncio
import tempfile
from traceback import print_exc
from typing import Optional, Tuple

import discord
from discord.ext import commands, tasks

from config import config
from musicbot.bot import MusicBot

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRACKED_PLAYERS_FILE = os.path.join(DATA_DIR, "lista_stats_lol.txt")
LOW_DMG_EXCEPTIONS_FILE = os.path.join(DATA_DIR, "excepciones_poquito_dmg.txt")


def _check_control_wards(match_detail: dict, puuid: str) -> Optional[int]:
    if match_detail["info"]["gameMode"] != "CLASSIC":
        return None
    for row in match_detail["info"]["participants"]:
        if row["puuid"] == puuid:
            return int(row["visionWardsBoughtInGame"])
    return None


def _check_damage(
    match_detail: dict, puuid: str
) -> Tuple[str, str, Optional[str]]:
    """Returns (damage_label, champion_name, image_path_or_none).

    damage_label is one of "poco", "mucho", "normal".
    """
    participants = [
        {
            "damage": row["totalDamageDealtToChampions"],
            "puuid": row["puuid"],
            "champ": row["championName"],
            "team": row["teamId"],
            "summonerName": row.get("riotIdGameName") or row.get("summonerName", ""),
        }
        for row in match_detail["info"]["participants"]
    ]

    summoner = next((p for p in participants if p["puuid"] == puuid), None)
    if summoner is None:
        return "normal", "", None

    summoner_team = summoner["team"]
    champ = summoner["champ"]

    max_p = max(participants, key=lambda p: p["damage"])
    allied = [p for p in participants if p["team"] == summoner_team]
    min_p = min(allied, key=lambda p: p["damage"])

    if min_p["puuid"] == puuid:
        path = _make_progress_bars(
            [p["damage"] for p in allied],
            [p["champ"] for p in allied],
            champ,
        )
        return "poco", champ, path
    if max_p["puuid"] == puuid:
        path = _make_progress_bars(
            [p["damage"] for p in allied],
            [p["champ"] for p in allied],
            champ,
            max_dmg=True,
        )
        return "mucho", champ, path
    return "normal", champ, None


def _make_progress_bars(
    damages, champs, summ_champ, max_dmg=False
) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    color, high_color = "#20acbc", "#1a8a96"
    if max_dmg:
        color, high_color = high_color, color

    fig, ax = plt.subplots(facecolor="#303338")
    bars = ax.barh(champs, damages, color=color)
    for i, name in enumerate(champs):
        if name == summ_champ:
            bars[i].set_color(high_color)

    ax.patch.set_facecolor("#303338")
    plt.box(False)
    ax.xaxis.set_visible(False)
    for i, v in enumerate(damages):
        ax.text(v + 1000, i - 0.1, str(v), color="#ffffff", fontsize=12)
    ax.set_yticks(range(len(champs)))
    ax.set_yticklabels(champs, fontsize=12, color="#ffffff")
    fig.subplots_adjust(left=0.2, top=0.99, bottom=0.01)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        plt.savefig(tmp.name, dpi=300)
    finally:
        plt.close(fig)
        tmp.close()
    return tmp.name


class StatsLol(commands.Cog):
    def __init__(self, bot: MusicBot):
        from riotwatcher import LolWatcher

        self.bot = bot
        self.region = config.RIOT_REGION
        self.watcher = LolWatcher(config.RIOT_API_KEY)
        self.chat: Optional[discord.TextChannel] = None

        with open(TRACKED_PLAYERS_FILE, "r") as f:
            self._tracked_raw = f.read()
        with open(LOW_DMG_EXCEPTIONS_FILE, "r") as f:
            self.exceptions = f.read().split()

    async def cog_load(self):
        self.stats_lol.start()

    async def cog_unload(self):
        self.stats_lol.cancel()

    async def _matchlist(self, puuid: str):
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self.watcher.match.matchlist_by_puuid(self.region, puuid),
        )

    async def _match_detail(self, match_id: str):
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self.watcher.match.by_id(self.region, match_id),
        )

    async def _send_image(self, content: str, path: str):
        try:
            with open(path, "rb") as f:
                await self.chat.send(content=content, file=discord.File(f))
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    @tasks.loop(seconds=120)
    async def stats_lol(self):
        if self.chat is None:
            return

        rows = self._tracked_raw.split("\n")
        for row in rows:
            if not row.strip():
                continue
            try:
                await self._handle_player_row(row)
            except Exception:
                print_exc()

    async def _handle_player_row(self, row: str):
        nombre, puuid, last_analized_game = row.split(",", 2)

        matches = await self._matchlist(puuid)
        if not matches:
            return
        last_match = matches[0]
        if last_match == last_analized_game:
            return

        detail = await self._match_detail(last_match)
        gamemode = detail["info"]["gameMode"]

        # ignore remakes
        if detail["info"]["gameDuration"] >= 360:
            damage, champ, img_path = _check_damage(detail, puuid)

            if gamemode == "CHERRY":
                for participant in detail["info"]["participants"]:
                    if participant["puuid"] == puuid:
                        place = participant.get("subteamPlacement")
                        if place == 8:
                            await self.chat.send(
                                f"{nombre} salió octavo en arena con {champ} :clown:"
                            )
                        elif place == 1:
                            await self.chat.send(
                                f"{nombre} ganó un arena con {champ} :sunglasses:"
                            )
            elif gamemode != "ARAM":
                if damage == "poco" and champ not in self.exceptions and img_path:
                    await self._send_image(
                        f"El daño de {nombre} con {champ} :clown:", img_path
                    )
                elif damage == "mucho" and img_path:
                    await self._send_image(
                        f"{nombre} ese daño ta nashi :dart:", img_path
                    )

                wards = _check_control_wards(detail, puuid)
                if wards == 0:
                    await self.chat.send(
                        f"{nombre} puso :zero: control wards :wheelchair:"
                    )
                elif wards == 1:
                    await self.chat.send(
                        f"{nombre} puso :one: control ward :face_vomiting:"
                    )

        replaced_row = row.replace(last_analized_game, last_match)
        self._tracked_raw = self._tracked_raw.replace(row, replaced_row)
        with open(TRACKED_PLAYERS_FILE, "w") as f:
            f.write(self._tracked_raw)

    @stats_lol.before_loop
    async def _before_stats(self):
        await self.bot.wait_until_ready()
        if config.STATS_LOL_CHAT_ID:
            self.chat = self.bot.get_channel(config.STATS_LOL_CHAT_ID)


async def setup(bot: MusicBot):
    if not config.ENABLE_STATS_LOL:
        return
    if not config.RIOT_API_KEY:
        print("stats_lol: RIOT_API_KEY not set, skipping cog load.")
        return
    await bot.add_cog(StatsLol(bot))
