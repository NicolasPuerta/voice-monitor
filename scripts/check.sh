#!/usr/bin/env bash
# Runs all quality checks: pytest, flake8, mypy and pylint.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> pytest"
python -m pytest
echo "==> flake8"
python -m flake8 app tests
echo "==> mypy"
python -m mypy
echo "==> pylint"
python -m pylint app tests
echo "All checks passed."
