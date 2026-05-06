#!/bin/bash
# Entropy corpus: Log rotation script
# Simulates a typical system admin log rotation utility

LOG_DIR="/var/log/myapp"
MAX_FILES=10
COMPRESS_AFTER=3

rotate_logs() {
    local dir="${1}"
    local max="${2}"
    local files
    files=$(find "${dir}" -name "*.log" -type f | sort -t'.' -k2 -n -r)
    local count=0
    for file in ${files}; do
        count=$((count + 1))
        if [ "${count}" -gt "${max}" ]; then
            rm -f "${file}"
            echo "Removed old log: ${file}"
        elif [ "${count}" -gt "${COMPRESS_AFTER}" ]; then
            if [ ! -f "${file}.gz" ]; then
                gzip "${file}"
                echo "Compressed: ${file}"
            fi
        fi
    done
}

check_disk_space() {
    local threshold="${1:-90}"
    local usage
    usage=$(df "${LOG_DIR}" | tail -1 | awk '{print $5}' | tr -d '%')
    if [ "${usage}" -gt "${threshold}" ]; then
        echo "WARNING: Disk usage at ${usage}%"
        return 1
    fi
    return 0
}

if [ -d "${LOG_DIR}" ]; then
    check_disk_space 85
    rotate_logs "${LOG_DIR}" "${MAX_FILES}"
    echo "Log rotation complete: $(date)"
fi
