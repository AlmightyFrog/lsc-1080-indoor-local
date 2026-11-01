#!/bin/sh
# TIME=<ip>|off - set the clock once at boot from the HTTP Date: header of
# that IP (plain TCP port 80; no DNS, no hostname, ever). ~1 s resolution;
# 6 attempts, 15 s apart, then gives up.
# Default 1.1.1.1 = Cloudflare anycast: NOT LOCAL; see TIME in hack.conf.

SD_DIR="/tmp/sd"
CFG_FILE="${SD_DIR}/custom/configs/hack.conf"

TIME=1.1.1.1
. "${CFG_FILE}" 2>/dev/null
[ "${TIME}" = "off" ] && exit 0

TRY=0
while [ "${TRY}" -lt 6 ]; do
    TRY=$((TRY + 1))
    D=$(printf 'HEAD / HTTP/1.0\r\n\r\n' | nc -w 8 "${TIME}" 80 2>/dev/null \
        | grep -i '^date:')
    E=$(echo "$D" | awk '
      # epoch math: days-from-civil algorithm, Howard Hinnant (public domain)
      BEGIN { m["Jan"]=1;m["Feb"]=2;m["Mar"]=3;m["Apr"]=4;m["May"]=5;m["Jun"]=6;
              m["Jul"]=7;m["Aug"]=8;m["Sep"]=9;m["Oct"]=10;m["Nov"]=11;m["Dec"]=12 }
      function dfc(y, mo, d,  era, yoe, doy, doe) {
        y -= (mo <= 2); era = int((y >= 0 ? y : y - 399) / 400); yoe = y - era * 400
        doy = int((153 * (mo + (mo > 2 ? -3 : 9)) + 2) / 5) + d - 1
        doe = yoe * 365 + int(yoe / 4) - int(yoe / 100) + doy
        return era * 146097 + doe - 719468 }
      { split($6, t, ":"); print dfc($5 + 0, m[$4], $3 + 0) * 86400 + t[1] * 3600 + t[2] * 60 + t[3] }')
    if [ -n "${E}" ] && [ "${E}" -gt 1000000000 ] 2>/dev/null; then
        date -u -s "@${E}" >/dev/null 2>&1 && exit 0
    fi
    sleep 15
done
exit 1
