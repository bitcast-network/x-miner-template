#!/bin/sh
set -eu

wallet_base="${WALLET_PATH:-${BITCAST_X_WALLET_PATH:-/home/miner/.bittensor/wallets}}"
wallet_name="${WALLET_NAME:-${BITCAST_X_WALLET_NAME:-default}}"
hotkey_name="${HOTKEY_NAME:-${BITCAST_X_WALLET_HOTKEY:-default}}"
wallet_dir="${wallet_base}/${wallet_name}"
hotkey_dir="${wallet_dir}/hotkeys"

mkdir -p "${hotkey_dir}"
if [ -z "${HOTKEY_DATA:-}" ]; then
    echo "[entrypoint] ERROR: HOTKEY_DATA is required" >&2
    exit 1
fi
printf '%s' "${HOTKEY_DATA}" | base64 -d > "${hotkey_dir}/${hotkey_name}"
chmod 0600 "${hotkey_dir}/${hotkey_name}"

if [ -n "${COLDKEYPUB_DATA:-}" ]; then
    printf '%s\n' "${COLDKEYPUB_DATA}" > "${wallet_dir}/coldkeypub.txt"
    chmod 0644 "${wallet_dir}/coldkeypub.txt"
fi

unset HOTKEY_DATA
exec x-miner-template "$@"
