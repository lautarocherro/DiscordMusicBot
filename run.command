#!/bin/bash
# Get the directory where the .command file is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Change to that directory
cd "$SCRIPT_DIR"

# Run the Python script
./.venv/bin/python run.py
