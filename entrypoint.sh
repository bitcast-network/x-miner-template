#!/bin/sh
set -eu

wallet_base="${WALLET_PATH:-${BITCAST_X_WALLET_PATH:-/home/miner/.bittensor/wallets}}"
wallet_name="${WALLET_NAME:-${BITCAST_X_WALLET_NAME:-default}}"
hotkey_name="${HOTKEY_NAME:-${BITCAST_X_WALLET_HOTKEY:-default}}"
wallet_dir="${wallet_base}/${wallet_name}"
hotkey_dir="${wallet_dir}/hotkeys"

mkdir -p "${hotkey_dir}"
if [ -n "${HOTKEY_DATA:-}" ]; then
    printf '%s' "${HOTKEY_DATA}" | base64 -d > "${hotkey_dir}/${hotkey_name}"
    chmod 0600 "${hotkey_dir}/${hotkey_name}"
elif [ ! -f "${hotkey_dir}/${hotkey_name}" ]; then
    echo "[entrypoint] ERROR: HOTKEY_DATA or an existing hotkey file is required" >&2
    exit 1
fi

if [ -n "${X_MINER_EXPECTED_HOTKEY:-}" ]; then
    python - "${hotkey_dir}/${hotkey_name}" "${X_MINER_EXPECTED_HOTKEY}" <<'PY'
import json
import sys

keyfile_path, expected_hotkey = sys.argv[1:]
try:
    with open(keyfile_path, encoding="utf-8") as keyfile:
        keyfile_data = json.load(keyfile)
except (OSError, ValueError) as error:
    raise SystemExit("[entrypoint] ERROR: HOTKEY_DATA is not a valid JSON keyfile") from error

if keyfile_data.get("ss58Address") != expected_hotkey:
    raise SystemExit("[entrypoint] ERROR: HOTKEY_DATA does not match X_MINER_EXPECTED_HOTKEY")
PY
fi

if [ -n "${COLDKEYPUB_DATA:-}" ]; then
    printf '%s\n' "${COLDKEYPUB_DATA}" > "${wallet_dir}/coldkeypub.txt"
    chmod 0644 "${wallet_dir}/coldkeypub.txt"
fi

unset HOTKEY_DATA
exec x-miner-template "$@"
