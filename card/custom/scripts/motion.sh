#!/bin/sh
# MOTION=1 -> supervisor for motiond. Reads hack.conf every respawn.

SD_DIR="/tmp/sd"
CUSTOM_DIR="${SD_DIR}/custom"
CFG_FILE="${CUSTOM_DIR}/configs/hack.conf"
BIN="${CUSTOM_DIR}/bin/motiond"

norm_log() {
    if [ "${LOG}" = "1" ]; then
        mkdir -p "${SD_DIR}/logs" 2>/dev/null
        LOG="${SD_DIR}/logs/motiond.log"
    else
        LOG=/dev/null
    fi
}
log() { echo "[$(date)] motion.sh: $*" >>"${LOG}"; }

MOTION=1
LOG=off
. "${CFG_FILE}" 2>/dev/null
norm_log

[ "${MOTION}" = "1" ] || exit 0
[ -x "${BIN}" ] || { log "missing ${BIN}"; exit 1; }

# SINGLETON: each failed open of the stats node leaks one driver slot
# (counter incremented, -EBUSY returned, never unwound by the vendor driver);
# enough failures kill the node until a power cycle. First instance wins.
LOCK=/tmp/.motiond.lock
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    exit 0
fi
echo "$$" >"$LOCK"

sleep 45   # let the ISP pipeline come up

while :; do
    MOTION=1; MOTION_ABS=1200; MOTION_MULT=3; MOTION_MINB=2
    MOTION_WIN=6; MOTION_NEED=3; MOTION_HOLD=4
    MOTION_PORT=5514; MOTION_CTRL=5515
    . "${CFG_FILE}" 2>/dev/null
    norm_log   # sourcing sets LOG back to the raw toggle - renormalize
    [ "${MOTION}" = "1" ] || { sleep 30; continue; }

    # Never hold the stats node while anyka_ipc (re)starts: killing the app
    # with our vb2 stream active wedges the ISP teardown path; RTSP stays dead
    # until a power cycle. App gone -> motiond stops.
    pidof anyka_ipc >/dev/null 2>&1 || { sleep 5; continue; }

    T0=$(cut -d. -f1 /proc/uptime)
    "${BIN}" --abs "${MOTION_ABS}" --mult "${MOTION_MULT}" --minb "${MOTION_MINB}" \
             --win "${MOTION_WIN}" --need "${MOTION_NEED}" --hold "${MOTION_HOLD}" \
             --port "${MOTION_PORT}" --ctrl-port "${MOTION_CTRL}" >>"${LOG}" 2>&1 &
    MDPID=$!
    while pidof anyka_ipc >/dev/null 2>&1 && kill -0 "$MDPID" 2>/dev/null; do
        sleep 2
    done
    kill "$MDPID" 2>/dev/null
    wait "$MDPID" 2>/dev/null
    RUN=$(( $(cut -d. -f1 /proc/uptime) - T0 ))
    log "motiond exited (ran ${RUN}s), stats node released"
    # exit under 15 s indicates failed opens (EBUSY/leak); back off to avoid
    # exhausting driver slots
    [ "$RUN" -lt 15 ] && sleep 60
    while ! pidof anyka_ipc >/dev/null 2>&1; do sleep 5; done
    sleep 30
done
