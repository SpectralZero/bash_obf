#!/bin/bash
# Entropy corpus: Service health check
# Typical monitoring/health check pattern

SERVICES=("nginx" "postgresql" "redis" "memcached")
ALERT_EMAIL="admin@example.com"
CHECK_INTERVAL=30
MAX_RETRIES=3

check_service() {
    local service="${1}"
    if systemctl is-active --quiet "${service}" 2>/dev/null; then
        return 0
    fi
    return 1
}

restart_service() {
    local service="${1}"
    local attempt=0
    while [ "${attempt}" -lt "${MAX_RETRIES}" ]; do
        attempt=$((attempt + 1))
        echo "[$(date '+%H:%M:%S')] Restart attempt ${attempt} for ${service}"
        systemctl restart "${service}" 2>/dev/null
        sleep 5
        if check_service "${service}"; then
            echo "[OK] ${service} recovered"
            return 0
        fi
    done
    return 1
}

send_alert() {
    local subject="${1}"
    local body="${2}"
    echo "${body}" | mail -s "${subject}" "${ALERT_EMAIL}" 2>/dev/null
}

main() {
    for service in "${SERVICES[@]}"; do
        if ! check_service "${service}"; then
            echo "[WARN] ${service} is down"
            if ! restart_service "${service}"; then
                send_alert "Service Down: ${service}" \
                    "Failed to restart ${service} after ${MAX_RETRIES} attempts on $(hostname)"
            fi
        else
            echo "[OK] ${service}"
        fi
    done
}

main
