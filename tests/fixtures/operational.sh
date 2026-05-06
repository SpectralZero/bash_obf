#!/bin/bash
# Fixture: Simulated operational script (curl download, cron, persistence)
target_url="http://example.com/config.json"
output_path="/tmp/config_${$}.json"
log_file="/var/log/setup.log"
retry_count=3

download_config() {
    local url="${1}"
    local dest="${2}"
    local attempt=0
    while [ "${attempt}" -lt "${retry_count}" ]; do
        attempt=$((attempt + 1))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Attempt ${attempt}/${retry_count}"
        if command -v curl >/dev/null 2>&1; then
            curl -sS -o "${dest}" "${url}" && return 0
        elif command -v wget >/dev/null 2>&1; then
            wget -q -O "${dest}" "${url}" && return 0
        fi
        sleep $((attempt * 2))
    done
    return 1
}

install_cron() {
    local schedule="${1}"
    local cmd="${2}"
    (crontab -l 2>/dev/null; echo "${schedule} ${cmd}") | sort -u | crontab -
}

main() {
    echo "=== Configuration Setup ==="
    if download_config "${target_url}" "${output_path}"; then
        echo "[+] Config downloaded to ${output_path}"
        chmod 600 "${output_path}"
    else
        echo "[-] Download failed after ${retry_count} attempts"
        exit 1
    fi
    echo "[*] Setup complete"
}

main "$@" 2>&1 | tee -a "${log_file}"
