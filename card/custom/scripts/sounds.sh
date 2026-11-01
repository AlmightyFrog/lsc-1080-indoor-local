#!/bin/sh
# MUTE_FACTORY_PROMPT=1 -> silence factory-mode voice files by
# bind-mounting silent.mp3 over them. Runs before the app starts.

SD_DIR="/tmp/sd"
SILENT="${SD_DIR}/custom/audio/silent.mp3"
CFG_FILE="${SD_DIR}/custom/configs/hack.conf"

MUTE_FACTORY_PROMPT=1
MUTE_ALL_SOUNDS=0
. "${CFG_FILE}" 2>/dev/null

[ -f "${SILENT}" ] || exit 0

if [ "${MUTE_ALL_SOUNDS}" = "1" ]; then
    for f in /usr/share/*.mp3; do
        [ -f "$f" ] && mount --bind "${SILENT}" "$f" 2>/dev/null
    done
elif [ "${MUTE_FACTORY_PROMPT}" = "1" ]; then
    for f in /usr/share/hutong_sound2.mp3 \
             /usr/share/8k16_cn_factory_enter_factory_mode.mp3 \
             /usr/share/8k16_cn_factory_speaker_test_voice.mp3; do
        [ -f "$f" ] && mount --bind "${SILENT}" "$f" 2>/dev/null
    done
fi
