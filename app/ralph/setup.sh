#!/bin/bash
# Ralph development environment setup
#
# Usage: ./setup.sh [--dev]
#   --dev  Install development dependencies (pytest, mypy, etc.)

set -euo pipefail

cd "$(dirname "$0")"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
if [[ "${1:-}" == "--dev" ]]; then
    echo "Installing development dependencies..."
    pip install -r requirements-dev.txt
else
    echo "Installing core dependencies..."
    pip install -r requirements.txt
fi

echo ""
echo "Setup complete!"
echo ""
echo "To activate the virtual environment:"
echo "  source app/ralph/.venv/bin/activate"
echo ""
echo "To run ralph:"
echo "  python -m ralph --help"
echo ""
echo "To run tests:"
echo "  pytest app/ralph/tests/"
