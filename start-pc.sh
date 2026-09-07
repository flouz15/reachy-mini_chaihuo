#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/chaihuo-reachy ]]; then
  echo "Missing .venv. Run: uv sync --python /usr/bin/python3.10 --extra dev --no-install-package pygobject" >&2
  exit 1
fi

# USB / in-car: pick the Reachy Mini XMOS by name. Device indexes change
# after replug, so never keep REACHY_AUDIO_DEVICE=default or a stale number.
resolve_reachy_serial_port() {
  local configured="${REACHY_DAEMON_SERIAL_PORT:-}"
  if [[ -n "${configured}" && -e "${configured}" ]]; then
    printf '%s\n' "${configured}"
    return 0
  fi

  local candidate
  shopt -s nullglob
  for candidate in /dev/serial/by-id/*USB_Single_Serial* /dev/serial/by-id/*1a86* /dev/ttyACM*; do
    if [[ -e "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      shopt -u nullglob
      return 0
    fi
  done
  shopt -u nullglob
  return 1
}

REACHY_SERIAL_PORT="$(resolve_reachy_serial_port || true)"
if [[ -n "${REACHY_SERIAL_PORT}" ]]; then
  export REACHY_DAEMON_SERIAL_PORT="${REACHY_SERIAL_PORT}"
  export REACHY_AUDIO_DEVICE="${REACHY_AUDIO_DEVICE_OVERRIDE:-auto}"
  export REACHY_AUDIO_INPUT_CHANNEL="${REACHY_AUDIO_INPUT_CHANNEL_OVERRIDE:-1}"
  export REACHY_CAMERA_DEVICE="${REACHY_CAMERA_DEVICE_OVERRIDE:-auto}"
  # PCM,0 is the stereo speaker path. PCM,1 is a joined mono control and
  # raising it alone leaves the actual output around -23 dB.
  if amixer -c Audio sget 'PCM',0 >/dev/null 2>&1; then
    amixer -q -c Audio sset 'PCM',0 90%
  fi
  if amixer -c Audio sget 'PCM',1 >/dev/null 2>&1; then
    amixer -q -c Audio sset 'PCM',1 90%
  fi
  echo "Reachy Mini detected at ${REACHY_SERIAL_PORT}; using robot USB camera/mic/speaker."
  args=(dashboard --target mac)
else
  args=(dashboard --target mac --standalone)
  echo "Reachy Mini serial not found; starting PC standalone mode."
fi

exec .venv/bin/chaihuo-reachy "${args[@]}"
