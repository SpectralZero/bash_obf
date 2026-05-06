#!/bin/bash
# Entropy corpus: Backup script
# Standard filesystem backup with rsync

BACKUP_SRC="/home/deploy/app"
BACKUP_DST="/mnt/backup/daily"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_DST}/${TIMESTAMP}"
LOCK_FILE="/var/run/backup.lock"
LOG_FILE="/var/log/backup.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

acquire_lock() {
    if [ -f "${LOCK_FILE}" ]; then
        local pid
        pid=$(cat "${LOCK_FILE}")
        if kill -0 "${pid}" 2>/dev/null; then
            log "ERROR: Backup already running (PID ${pid})"
            return 1
        fi
        log "WARN: Stale lock file removed"
    fi
    echo $$ > "${LOCK_FILE}"
    return 0
}

release_lock() {
    rm -f "${LOCK_FILE}"
}

cleanup_old() {
    log "Cleaning backups older than ${RETENTION_DAYS} days"
    find "${BACKUP_DST}" -maxdepth 1 -type d -mtime +${RETENTION_DAYS} -exec rm -rf {} \;
}

run_backup() {
    mkdir -p "${BACKUP_DIR}"
    log "Starting backup: ${BACKUP_SRC} -> ${BACKUP_DIR}"
    rsync -avz --delete \
        --exclude='.git' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        "${BACKUP_SRC}/" "${BACKUP_DIR}/"
    local rc=$?
    if [ "${rc}" -eq 0 ]; then
        log "Backup completed successfully"
        ln -sfn "${BACKUP_DIR}" "${BACKUP_DST}/latest"
    else
        log "ERROR: Backup failed with exit code ${rc}"
    fi
    return "${rc}"
}

trap release_lock EXIT
if acquire_lock; then
    cleanup_old
    run_backup
fi
