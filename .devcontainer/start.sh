#!/usr/bin/env bash
set -euo pipefail
# No model calls, dispatches or repository mutations at startup.
if [ "${CODESPACES:-}" != true ]; then exit 0; fi
mkdir -p /workspaces/.387-news-owner-review
chmod 700 /workspaces/.387-news-owner-review
nohup .venv/bin/python -m scripts.codespace41 --serve > /workspaces/.387-news-owner-review/panel.log 2>&1 < /dev/null &
