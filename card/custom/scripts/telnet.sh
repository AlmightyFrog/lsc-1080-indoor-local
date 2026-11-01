#!/bin/sh
# TELNET=1 -> persistent no-login root telnetd on TELNET_PORT.

SD_DIR="/tmp/sd"
CFG_FILE="${SD_DIR}/custom/configs/hack.conf"
LOG="${SD_DIR}/logs/telnet.log"

TELNET=1
TELNET_PORT=24
LOG=off
. "${CFG_FILE}" 2>/dev/null
[ "${LOG}" = "1" ] || LOG=/dev/null
[ "${TELNET}" = "1" ] || exit 0

# single supervisor (entrypoint could be started twice by odd boot order)
LOCK=/tmp/.telnetd.lock
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    exit 0
fi
echo $$ >"$LOCK"

while :; do
    ps | grep -v grep | grep -q "telnetd -p ${TELNET_PORT}" || {
        telnetd -p "${TELNET_PORT}" -l /bin/sh
        echo "[$(date)] telnetd :${TELNET_PORT}" >>"${LOG}" 2>&1
    }
    sleep 2
done
