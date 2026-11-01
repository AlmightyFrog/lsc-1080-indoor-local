# LSC 1080p indoor cam — local RTSP + root, zero flash writes

LSC/Tuya indoor camera (Anyka AK3918AV130, fw 6.28xx) as a local IP camera:
RTSP video, root shell, on-device motion detection, no cloud. All code runs
from the microSD card; flash is never written.

The Tuya/LSC app cannot pair with or reach the camera while `OFFLINE`/
`DNS_BLOCK` are active: local-only by design.

Tested on: LSC 1080p indoor cam (Anyka/Tuya board), fw 6.2802.78.158.

## Credits

The SD boot mechanism, marker files, `hostapd` hook, `hack.sh`/`custom/` card
layout, and the offline-hosts / telnetd / sound-mute tricks are from
**[tasarren/lsc-tuya-toolkit](https://github.com/tasarren/lsc-tuya-toolkit)**.
That work stands on the original platform findings in
**[guino/LSCOutdoor1080P](https://github.com/guino/LSCOutdoor1080P)** - the
`_ht_ap_mode.conf`/`hostapd` hijack, factory mode, shadow telnet - itself a
successor of [guino/Merkury1080P](https://github.com/guino/Merkury1080P).
This repo adds: color day+night, DNS poison, on-device motion detection,
PC tools.

Written mostly by an AI coding agent; everything verified on real hardware.

## Flash (Linux)

DANGER Zone: `/dev/mmcblkX` is a placeholder: replace `X` with the card number from
`lsblk`. Copy-pasted commands fail by purpose (no such device). `wipefs` and `sfdisk`
destroy everything on the device you give them.

Partition, format, mount — microSD:
```sh
sudo wipefs -a /dev/mmcblkX
printf 'label: dos\nstart=2048, type=c\n' | sudo sfdisk -W always /dev/mmcblkX
sudo mkfs.vfat -F 32 /dev/mmcblkXp1
sudo fsck.fat -wy /dev/mmcblkXp1
sudo mkdir -p /mnt/lsc
sudo mount /dev/mmcblkXp1 /mnt/lsc
```

Copy files and edit wifi/ip config:
```sh
sudo cp -r card/* /mnt/lsc/
# Edit WIFI and IP config
sudo vim /mnt/lsc/_ak39_factory.ini
```

Sync and unmount:
```
sync
sudo umount /mnt/lsc
```

Insert card into the powered-off camera, power on, wait, boot can take more than 1 minute:
```sh
ping <cam-ip>
telnet <cam-ip> 24
ffplay rtsp://<cam-ip>:554/main_ch
```

In case of problems check microSD `logs/` folder (`LOG=1` in `custom/configs/hack.conf` must be enabled; default is `off` to reduce microSD wear).

## Endpoints

| endpoint | what |
|---|---|
| `rtsp://<cam-ip>:554/main_ch` | 1080p H.264 + AAC |
| `telnet <cam-ip> 24` | root shell, no login |
| `telnet <cam-ip> 23` | root/`telnet` (stock factory telnet) |
| `tcp <cam-ip> 8090` | stock factory control service (unauthenticated) |
| UDP broadcast `:5514` | motion events, one JSON line per start/stop |
| `tcp <cam-ip> 5515` | motion grid telemetry (`camtool.py live`) |
| `/tmp/motion.status` on cam | current state, one JSON line |

## Configure

Toggles: `card/custom/configs/hack.conf` (apply by power-cycle; `MOTION_*`
keys re-apply on every motiond respawn). Wi-Fi/IP: `card/_ak39_factory.ini`.
Additional daemons: add a start line to `card/custom/scripts/entrypoint.sh`.

| key | meaning |
|---|---|
| `OFFLINE=1` | hosts entries point listed Tuya endpoints at 127.0.0.1 |
| `DNS_BLOCK=1` | resolv.conf poisoned (`nameserver 127.0.0.1`): no name resolves, implies OFFLINE's effect |
| `ISP_COLOR=1` | color in any light; `0` = stock AUTO (color day, B&W dark night) |
| `OVERRIDE_HW_SETTINGS=1` | bind board ini; drives `night_mode_def` per `ISP_COLOR` |
| `TELNET=1` `TELNET_PORT=24` | no-login root telnet |
| `LED=off` | state LED: `off`, `solid`, `blink` (= stock) |
| `MUTE_FACTORY_PROMPT=1` | silence factory-mode voice prompts |
| `MUTE_ALL_SOUNDS=0` | `1` mutes every `/usr/share/*.mp3`, alarm sounds included |
| `MOTION=1` | motion daemon (tuning keys in `hack.conf`) |
| `TIME=1.1.1.1` | clock sync once at boot from the HTTP `Date:` header of that IP; default `1.1.1.1` is a **non-local endpoint** — a LAN IP (any HTTP responder on port 80) avoids WAN traffic; `off` disables; never uses DNS; unreachable endpoint leaves the clock at 2000-01-01 |
| `LOG=off` | `1` writes per-boot logs to card `logs/`; off spares the FAT |

## PC tools (Python, run with [uv](https://docs.astral.sh/uv/))

```sh
uv run tools/camtool.py status <cam-ip>           # ports, uptime, motiond, RTSP + chroma
uv run tools/camtool.py snap <cam-ip> -o snap.jpg # single RTSP frame
uv run tools/camtool.py shell <cam-ip>            # telnet
```

## Motion detection

The ISP computes a 32×24 grid of per-block frame differences for its 3DNR
engine and exposes it as a V4L2 node (`/dev/isp-stats-3dnr-0`) that the stock
app never opens. `motiond` (`tools/motiond.c`, ARMv5 static binary on the
card) averages it to 6×8 superblocks, learns a per-superblock noise floor,
and emits debounced start/stop events. It shares the ISP pipeline with the
vendor app: when `anyka_ipc` stops, motiond stops too (releasing the node is
required for a clean app restart).

Event format (UDP broadcast):

```json
{"ev":"motion","state":"start","score":20019,"blocks":12,"ts":123456}
```

Consumers: Home Assistant UDP sensor platform (port 5514), or:

```sh
uv run tools/camtool.py events              # listener; --port 5514, --hook <script>
uv run tools/camtool.py live <cam-ip>       # heatmap of the decision grid
```

## Rebuild / develop

```sh
make        # builds motiond + hello inside the pinned container (only
            # docker needed); fails if the shipped binary is no longer
            # byte-reproducible
make clean
```

Container toolchain: `https://musl.cc/armv5l-linux-musleabi-cross.tgz`,
sha256 pinned and verified in `tools/Dockerfile`.

Deploy binaries over tftp. On the PC, in a separate terminal that stays open:

```sh
uv run tools/tftpd_rw.py tools 6970
```

Cam (`telnet <cam-ip> 24`); `<PC-IP>` = this machine's LAN address:

```sh
# copy to camera
tftp -g -r hello -l /tmp/hello <PC-IP> 6970 && chmod +x /tmp/hello && /tmp/hello

# pull from camera
tftp -p -l /usr/local/isp_gc20c3.conf -r isp.bin <PC-IP> 6970
```


## How it works

Stock init honors SD-card marker files; no verified boot.

1. `_ak39_factory.ini` → factory test mode: Wi-Fi, static IP, RTSP server,
   telnet :23, all from firmware code paths that trust this file.
2. `_ht_ap_mode.conf` → init copies the card's `hostapd` to `/tmp/hostapd`
   and executes it as root; it runs `hack.sh`.
3. `hack.sh` bind-mounts the shadow file, board ini and ISP tuning, kills the
   video app (the firmware process monitor respawns it seconds later with the
   bound config in effect), then starts `custom/scripts/entrypoint.sh`:
   telnetd :24, hosts/resolv.conf poison (`offline.sh`), motiond, LED, and
   one-shot clock sync (`timed.sh`, see `TIME`).

All changes are bind-mounts or RAM-launched processes; gone on power-off.
`/etc/config` is jffs2 on flash and is never written — the resolv.conf poison
bind-mounts over the existing file, and binds skip missing targets.

## Limitations / Considerations

- The IR LEDs are never driven. `ISP_COLOR=1`: low light yields a dark, noisy
  color picture. `ISP_COLOR=0`: the firmware AUTO night style applies (B&W,
  equally dark).
- `telnet :24` is unauthenticated; stock `:23` uses root/`telnet`; `:8090` is
  an open factory service. Suitable only for networks under your control.

## License / provenance / disclaimer

MIT for code written in this repo. That grant does **not** cover:

- `card/shadow`, `card/custom/audio/silent.mp3` (redistributed unmodified),
  `card/_ht_ap_mode.conf` (empty marker) and the `hack.sh`/`entrypoint`/
  `telnet`/`offline`/`sounds` card skeleton — all from
  [tasarren/lsc-tuya-toolkit](https://github.com/tasarren/lsc-tuya-toolkit),
  derived from the findings in
  [guino/LSCOutdoor1080P](https://github.com/guino/LSCOutdoor1080P) /
  [guino/Merkury1080P](https://github.com/guino/Merkury1080P); none of the
  three declares a license. Removal on request.
- `card/custom/configs/_ht_hw_settings.ini` (board config from a device of
  this platform) and `card/custom/configs/sensor_isp_color.conf` (generated
  by `tools/make-isp-color.py` from the firmware file
  `/usr/local/isp_gc20c3.conf`; regenerate from a device of this model
  instead of relying on the shipped copy). Both are vendor firmware data;
  redistribution is the user's responsibility.

Use at your own risk; modifying devices may void warranty.
