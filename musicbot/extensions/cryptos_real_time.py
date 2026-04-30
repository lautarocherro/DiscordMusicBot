import asyncio
from traceback import print_exc

from discord.ext import commands, tasks

from config import config
from musicbot.bot import MusicBot


class CryptosRealTime(commands.Cog):
    """Renames voice channels with live BTC, ETH and Argentine 'Dolar Blue' prices."""

    BLUE_URL = "https://api.bluelytics.com.ar/v2/latest"

    def __init__(self, bot: MusicBot):
        self.bot = bot
        self._client = None

        self.btc_voice = None
        self.eth_voice = None
        self.blue_voice = None

        if config.BINANCE_API_KEY and config.BINANCE_API_SECRET:
            from binance.client import Client

            self._client = Client(
                config.BINANCE_API_KEY,
                config.BINANCE_API_SECRET,
                testnet=False,
            )

    async def cog_load(self):
        self.cryptos_real_time.start()
        self.get_dolar_blue.start()

    async def cog_unload(self):
        self.cryptos_real_time.cancel()
        self.get_dolar_blue.cancel()

    async def _get_coin_price(self, symbol: str) -> str:
        if self._client is None:
            return "0.00"

        def _fetch():
            return float(self._client.get_avg_price(symbol=symbol)["price"])

        price = await asyncio.get_running_loop().run_in_executor(None, _fetch)
        return f"{price:.2f}"

    @tasks.loop(seconds=300)
    async def cryptos_real_time(self):
        try:
            if self.eth_voice is not None:
                eth = await self._get_coin_price("ETHUSDT")
                await self.eth_voice.edit(name=f"𝓔𝓣𝓗: ${eth}")
            if self.btc_voice is not None:
                btc = await self._get_coin_price("BTCUSDT")
                await self.btc_voice.edit(name=f"𝓑𝓣𝓒: ${btc}")
        except Exception:
            print_exc()

    @cryptos_real_time.before_loop
    async def _before_cryptos(self):
        await self.bot.wait_until_ready()
        if config.CRYPTOS_BTC_VOICE_ID:
            self.btc_voice = self.bot.get_channel(config.CRYPTOS_BTC_VOICE_ID)
        if config.CRYPTOS_ETH_VOICE_ID:
            self.eth_voice = self.bot.get_channel(config.CRYPTOS_ETH_VOICE_ID)

    @tasks.loop(hours=4)
    async def get_dolar_blue(self):
        if self.blue_voice is None:
            return
        try:
            async with self.bot.client_session.get(self.BLUE_URL) as resp:
                resp.raise_for_status()
                data = await resp.json()
            blue_price = round(float(data["blue"]["value_sell"]), 2)
            await self.blue_voice.edit(name=f"𝓓𝓸́𝓵𝓪𝓻 𝓑𝓵𝓾𝓮: ${blue_price}")
        except Exception:
            print_exc()

    @get_dolar_blue.before_loop
    async def _before_blue(self):
        await self.bot.wait_until_ready()
        if config.CRYPTOS_BLUE_VOICE_ID:
            self.blue_voice = self.bot.get_channel(config.CRYPTOS_BLUE_VOICE_ID)


async def setup(bot: MusicBot):
    if not config.ENABLE_CRYPTOS_RT:
        return
    await bot.add_cog(CryptosRealTime(bot))
