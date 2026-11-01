#!/bin/sh
# OFFLINE=1   bind configs/hosts over /etc/hosts (listed Tuya endpoints
#             resolve to 127.0.0.1; with DNS_BLOCK=0 unlisted names still
#             resolve normally)
# DNS_BLOCK=1 bind configs/resolv.conf over /etc/config/resolv.conf. The stub
#             says nameserver 127.0.0.1 and nothing listens there: every
#             lookup fails immediately with connection-refused.

SD_DIR="/tmp/sd"
CUSTOM_DIR="${SD_DIR}/custom"
CFG_FILE="${CUSTOM_DIR}/configs/hack.conf"
LOG_FILE="${SD_DIR}/logs/offline.$(date +%Y%m%d_%H%M%S).log"

mkdir -p "${SD_DIR}/logs" 2>/dev/null
OFFLINE=1
DNS_BLOCK=1
LOG=off
. "${CFG_FILE}" 2>/dev/null
[ "${LOG}" = "1" ] || LOG_FILE=/dev/null
( exec >>"${LOG_FILE}" ) 2>/dev/null || LOG_FILE=/dev/null
exec >>"${LOG_FILE}" 2>&1
log() { echo "[$(date)] $*"; }

if [ "${OFFLINE}" = "1" ] && [ -f "${CUSTOM_DIR}/configs/hosts" ]; then
    if ! mount | grep -q " on /etc/hosts "; then
        mount --bind "${CUSTOM_DIR}/configs/hosts" /etc/hosts 2>/dev/null \
            && log "hosts bound" || log "hosts bind FAILED"
    fi
fi

# /etc/resolv.conf is a symlink to /etc/config/resolv.conf, and /etc/config is
# jffs2 = FLASH. Never write there: bind-mount the stub over the real file.
if [ "${DNS_BLOCK}" = "1" ] && [ -f "${CUSTOM_DIR}/configs/resolv.conf" ] && \
   [ -e /etc/config/resolv.conf ]; then
    if ! mount | grep -q " on /etc/config/resolv.conf "; then
        mount --bind "${CUSTOM_DIR}/configs/resolv.conf" /etc/config/resolv.conf 2>/dev/null \
            && log "resolv.conf bound (no name resolution)" || log "resolv bind FAILED"
    fi
fi
