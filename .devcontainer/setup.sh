#!/usr/bin/env bash
set -euo pipefail
python -m venv .venv
.venv/bin/python -m pip install -r .devcontainer/requirements.txt
.venv/bin/python -m playwright install --with-deps chromium
printf '%s\n' '387 News готова. Откройте Terminal → Run Task → «387 News: открыть панель». Gemini при установке не вызывается.'
