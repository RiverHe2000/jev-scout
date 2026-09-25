#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo 'Create .venv and install requirements.lock and the project first.' >&2
  exit 1
fi
if [ ! -f frontend/dist/index.html ]; then
  echo 'Run pnpm --dir frontend build first.' >&2
  exit 1
fi
exec .venv/bin/python -m jev_scout.cli serve
