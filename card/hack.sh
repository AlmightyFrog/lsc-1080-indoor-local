#!/bin/sh
# Runs as root early in boot (via the hostapd hook). Bind-mounts replacement
# config over the firmware's files, then starts custom/scripts/entrypoint.sh.
# Bind targets must already exist - creating a file under /etc/config would
# itself write to the jffs2 flash.

SD_DIR="/tmp/sd"
CUSTOM_DIR="${SD_DIR}/custom"
SCRIPTS_DIR="${CUSTOM_DIR}/scripts"
CONFIG_DIR="${CUSTOM_DIR}/configs"
CFG_FILE="${CONFIG_DIR}/hack.conf"
DATETIME="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${SD_DIR}/logs/run.${DATETIME}.log"

log() { echo "[$(date +%Y-%m-%dT%H:%M:%S)] $*"; }

mkdir -p "${SD_DIR}"
mount /dev/mmcblk0p1 "${SD_DIR}" 2>/dev/null || mount /dev/mmcblk0 "${SD_DIR}" 2>/dev/null
mkdir -p "${SD_DIR}/logs" 2>/dev/null
[ -d "${SD_DIR}/logs" ] || LOG_FILE=/tmp/hack.log
load_cfg() {
    ISP_COLOR=1
    OVERRIDE_HW_SETTINGS=1
    LOG=off
    . "${CFG_FILE}" 2>/dev/null
}

load_cfg
[ "${LOG}" = "1" ] || LOG_FILE=/dev/null
# a failed exec redirect kills this non-interactive shell outright, so probe
( exec >>"${LOG_FILE}" ) 2>/dev/null || LOG_FILE=/dev/null
exec >>"${LOG_FILE}" 2>&1
log "hack.sh start"

# keep the 5 newest log sets on the card (FAT + frequent power-cycles)
if [ "${LOG}" = "1" ]; then
    ls -1t "${SD_DIR}/logs"/run.*.log 2>/dev/null         | tail -n +6 | while read -r f; do rm -f "$f"; done
    ls -1t "${SD_DIR}/logs"/anyka_debug.*.log 2>/dev/null | tail -n +6 | while read -r f; do rm -f "$f"; done
fi

# mute factory-mode voice prompts before the app can play them
/bin/sh "${SCRIPTS_DIR}/sounds.sh" >/dev/null 2>&1

# root password "telnet" for the factory telnet on :23
[ -e /etc/config/shadow ] && mount --bind "${SD_DIR}/shadow" /etc/config/shadow 2>/dev/null

# Board config: night_mode_def = 0 AUTO | 1 IRLED | 2 COLOR (vendor doc in
# the ini). Derived in RAM from the SD ini.
if [ "${OVERRIDE_HW_SETTINGS}" = "1" ]; then
    cp "${CONFIG_DIR}/_ht_hw_settings.ini" /tmp/hw_settings.ini 2>/dev/null
    case "${ISP_COLOR}" in
      1) sed -i 's/^night_mode_def *=.*/night_mode_def = 2/' /tmp/hw_settings.ini ;;
      *) sed -i 's/^night_mode_def *=.*/night_mode_def = 0/' /tmp/hw_settings.ini ;;
    esac
    mount --bind /tmp/hw_settings.ini /usr/local/_ht_hw_settings.ini 2>/dev/null
fi

# ISP_COLOR=1: bind the ISP tuning whose night record is the day record.
# anyka_ipc only creates /tmp/sensor_isp.conf when absent.
if [ "${ISP_COLOR}" = "1" ]; then
    touch /tmp/sensor_isp.conf 2>/dev/null
    mount --bind "${CONFIG_DIR}/sensor_isp_color.conf" /tmp/sensor_isp.conf 2>/dev/null
fi

# vendor app log -> card, for post-mortems (LOG=1 only)
if [ "${LOG}" = "1" ] && [ -e /etc/config/log_debug ]; then
    touch "${SD_DIR}/logs/anyka_debug.${DATETIME}.log" 2>/dev/null
    mount --bind "${SD_DIR}/logs/anyka_debug.${DATETIME}.log" /etc/config/log_debug 2>/dev/null
fi

# Restart the video app so it picks up the binds (it caches config at
# startup); the firmware's own process monitor respawns it within seconds.
# drop_caches.sh: vendor page-cache loop, idle CPU burn past boot.
for p in $(ps | grep -F drop_caches | grep -v grep | awk '{print $1}'); do kill -9 "$p" 2>/dev/null; done
rm -f /tmp/drop_caches.sh 2>/dev/null
kill -TERM $(pidof anyka_ipc) 2>/dev/null

# the firmware starts anyka_ipc directly, with no wrapper to hook - launch
# our own service chain here
if [ -f "${SCRIPTS_DIR}/entrypoint.sh" ]; then
    ( /bin/sh "${SCRIPTS_DIR}/entrypoint.sh" >/dev/null 2>&1 & )
fi
log "hack.sh done"
