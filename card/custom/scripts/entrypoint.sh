#!/bin/sh
# Service chain, started by hack.sh after the config binds. Add your own
# daemons here. Each script reads hack.conf itself and no-ops when its
# toggle is off.

SD_DIR="/tmp/sd"
SCRIPTS_DIR="${SD_DIR}/custom/scripts"
CFG_FILE="${SD_DIR}/custom/configs/hack.conf"
LOG_FILE="${SD_DIR}/logs/entrypoint.$(date +%Y%m%d_%H%M%S).log"

mkdir -p "${SD_DIR}/logs" 2>/dev/null
LOG=off
. "${CFG_FILE}" 2>/dev/null
[ "${LOG}" = "1" ] || LOG_FILE=/dev/null
( exec >>"${LOG_FILE}" ) 2>/dev/null || LOG_FILE=/dev/null
exec >>"${LOG_FILE}" 2>&1
echo "[$(date)] entrypoint start"

/bin/sh "${SCRIPTS_DIR}/telnet.sh"  >/dev/null 2>&1 &
/bin/sh "${SCRIPTS_DIR}/offline.sh" >/dev/null 2>&1 &
/bin/sh "${SCRIPTS_DIR}/motion.sh"  >/dev/null 2>&1 &
/bin/sh "${SCRIPTS_DIR}/led.sh"     >/dev/null 2>&1 &
/bin/sh "${SCRIPTS_DIR}/timed.sh"   >/dev/null 2>&1
