#!/bin/sh
# LED=off|solid|blink - state LED control (blink = stock, do nothing).
# The firmware arms a kernel "timer" trigger on /sys/class/leds/state_led at
# app start and never re-arms it; re-asserting every 10 s also covers a later
# app restart.

SD_DIR="/tmp/sd"
CFG_FILE="${SD_DIR}/custom/configs/hack.conf"
LED_DIR=/sys/class/leds/state_led

LED=off
. "${CFG_FILE}" 2>/dev/null

[ -d "${LED_DIR}" ] || exit 0
case "${LED}" in off|solid) ;; *) exit 0 ;; esac

while :; do
    echo none >"${LED_DIR}/trigger" 2>/dev/null
    [ "${LED}" = off ] && B=0 || B=255
    echo "$B" >"${LED_DIR}/brightness" 2>/dev/null
    sleep 10
done
