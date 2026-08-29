#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/chaihuo-reachy ]]; then
  echo "Missing .venv. Run: uv sync --python /usr/bin/python3.10 --extra dev --no-install-package pygobject" >&2
  exit 1
fi

if [[ -e /dev/ttyACM0 ]] && amixer -c Audio sget 'PCM',1 >/dev/null 2>&1; then
  amixer -q -c Audio sset 'PCM',1 90%
fi

args=(dashboard --target mac)
if [[ -e /dev/ttyACM0 ]]; then
  echo "Reachy Mini detected at /dev/ttyACM0; starting hardware mode."
else
  args+=(--standalone)
  echo "Reachy Mini serial not found; starting PC standalone mode."
fi

exec .venv/bin/chaihuo-reachy "${args[@]}"
