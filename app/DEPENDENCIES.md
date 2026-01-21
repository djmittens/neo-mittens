# Ralph Python Package Dependencies

This document lists the dependencies required for the `ralph` Python package.

## Runtime Dependencies

| Dependency | Required | Purpose | Install |
|------------|----------|---------|---------|
| **python3** | Yes | Python 3.11+ runtime | Pre-installed on most systems |

## Development Dependencies

| Dependency | Required | Purpose | Install |
|------------|----------|---------|---------|
| **mypy** | Optional | Static type checking | `pip3 install --user mypy` or `brew install mypy` |
| **pytest** | Optional | Test framework | `pip3 install --user pytest` |
| **radon** | Optional | Code complexity analysis | `pip3 install --user radon` |

## Virtual Environment

For development, use the project's virtual environment:

```bash
# Activate the venv
source .venv/bin/activate

# Install dependencies
pip install mypy pytest radon

# Run mypy type checking
python -m mypy ralph --ignore-missing-imports
```

## Verification

```bash
# Check mypy is installed
python3 -m mypy --version

# Run type checks
cd app && python -m mypy ralph --ignore-missing-imports
```
