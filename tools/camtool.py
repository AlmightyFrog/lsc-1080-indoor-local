#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13"]
# ///
"""camtool - PC-side tools for the hacked LSC/Anyka cam.

usage (with uv):
  uv run camtool.py status [IP]                 health: ports, RTSP frame+chroma, motiond
  uv run camtool.py events [--port 5514]        live motion events (UDP) + optional hook
  uv run camtool.py live   [IP]                 live motion heatmap
  uv run camtool.py snap   [IP] [-o out.jpg]    grab one RTSP frame + report chroma
  uv run camtool.py shell  [IP]                 quick no-login telnet

All queries are LAN-side only (telnet :24 helper port, RTSP :554, UDP :5514, TCP :5515).
Nothing is written to the camera.
"""
import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

DEFAULT_IP = "10.42.0.54"


# ----------------------------------------------------------------- telnet ---
class CamShell:
    """Telnet client for the cam's no-login shell (port 24)."""

    def __init__(self, ip: str, port: int = 24, timeout: float = 4.0):
        self.s = socket.create_connection((ip, port), timeout)

    def _drain(self, wait: float, until_prompt: bool = False) -> str:
        self.s.settimeout(0.4)
        buf = b""
        end = time.time() + wait
        while time.time() < end:
            try:
                d = self.s.recv(4096)
            except socket.timeout:
                d = b""
            if d:
                buf += d
                if until_prompt and b"/ #" in buf[-20:]:
                    break
            elif until_prompt and b"/ #" in buf[-20:]:
                break
        txt = buf.replace(b"\x00", b"").decode("latin-1")
        txt = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", txt)
        return txt

    def cmd(self, c: str, wait: float = 1.2) -> str:
        self._drain(0.6, until_prompt=False)
        self.s.sendall((c + "\n").encode())
        out = self._drain(wait)
        # strip the echo of the command itself and trailing prompt
        lines = [l for l in out.splitlines() if c[:25] not in l and l.strip() not in ("/ #", "/tmp #")]
        return "\n".join(lines).strip()

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


# ------------------------------------------------------------------ utils ---
def tcp_open(ip: str, port: int, timeout: float = 1.5) -> bool:
    try:
        socket.create_connection((ip, port), timeout).close()
        return True
    except OSError:
        return False


def ffmpeg_capture(ip: str, out: str, timeout: int = 25) -> bool:
    try:
        r = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp",
             "-i", f"rtsp://{ip}:554/main_ch", "-frames:v", "1", "-y", out],
            capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def chroma_of(path: str) -> tuple[float, float] | None:
    try:
        r = subprocess.run(
            ["ffmpeg", "-loglevel", "info", "-i", path, "-vf",
             "signalstats,metadata=print:key=lavfi.signalstats.UAVG,"
             "metadata=print:key=lavfi.signalstats.VAVG", "-f", "null", "-"],
            capture_output=True, text=True, timeout=20)
        u = re.findall(r"UAVG=([\d.]+)", r.stderr)
        v = re.findall(r"VAVG=([\d.]+)", r.stderr)
        if u and v:
            return float(u[-1]), float(v[-1])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


# ----------------------------------------------------------------- status ---
def cmd_status(a):
    from rich.console import Console
    from rich.table import Table
    con = Console()
    ip = a.ip
    t = Table(title=f"LSC cam status — {ip}", header_style="bold cyan")
    t.add_column("check"); t.add_column("result")
    ok = lambda b, yes, no: f"[green]{yes}[/]" if b else f"[red]{no}[/]"  # noqa: E731
    for port, what in ((24, "helper shell"), (23, "factory telnet"), (554, "RTSP"), (8090, "factory ctl"), (5515, "motiond telemetry")):
        t.add_row(what, ok(tcp_open(ip, port), f"open :{port}", f"closed :{port}"))
    try:
        sh = CamShell(ip)
        up = sh.cmd("cut -d. -f1 /proc/uptime")
        t.add_row("uptime", up.splitlines()[0] + " s" if up else "?")
        pids = sh.cmd("echo $(pidof anyka_ipc) : $(pidof motiond)")
        parts = pids.split(":")
        app = parts[0].strip()
        md = parts[1].strip() if len(parts) > 1 else "?"
        t.add_row("anyka_ipc", ok(bool(app), f"pid {app}", "DEAD"))
        t.add_row("motiond", ok(bool(md), f"pid {md}", "not running"))
        st = sh.cmd("cat /tmp/motion.status 2>/dev/null")
        try:
            ev = json.loads(st.splitlines()[0])
            t.add_row("last motion", f"state={ev.get('state')} score={ev.get('score')} blocks={ev.get('blocks')}")
        except Exception:
            pass
        sh.close()
    except OSError as e:
        t.add_row("shell", f"[red]unreachable: {e}[/]")
    if shutil.which("ffmpeg"):
        con.print(t)
        con.print("[dim]grabbing an RTSP frame (this takes a few seconds)...[/]")
        out = f"/tmp/camtool_snap_{int(time.time())}.jpg"
        if ffmpeg_capture(ip, out):
            ch = chroma_of(out)
            chroma_txt = "grey picture (ISP_COLOR patch off?)" if ch and abs(ch[0] - 128) < 0.5 and abs(ch[1] - 128) < 0.5 \
                else (f"COLOR U={ch[0]} V={ch[1]}" if ch else "?")
            t2 = Table(header_style="bold green")
            t2.add_row("RTSP frame", f"[green]saved {out}[/]")
            t2.add_row("chroma", chroma_txt)
            con.print(t2)
        else:
            con.print("[red]RTSP frame capture FAILED (pipeline wedged? try power cycle)[/]")
    else:
        con.print(t)
        con.print("[yellow]ffmpeg not found — skipped stream test[/]")


# ----------------------------------------------------------------- events ---
def cmd_events(a):
    from rich.console import Console
    con = Console()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", a.port))
    con.print(f"[bold cyan]listening udp/{a.port} for motiond events (Ctrl-C quits)[/]")
    hooks = []
    try:
        while True:
            data, addr = s.recvfrom(2048)
            try:
                ev = json.loads(data.decode())
            except Exception:
                continue
            when = time.strftime("%H:%M:%S")
            if ev.get("state") == "start":
                con.print(f"[red]{when} {addr[0]}  ▶ MOTION START  score={ev.get('score', 0)} blocks={ev.get('blocks', 0)}[/]")
            else:
                con.print(f"[green]{when} {addr[0]}  ⏹ motion stop[/]")
            hooks = [h for h in hooks if h.poll() is None]   # reap finished hooks
            if a.hook:
                hooks.append(subprocess.Popen([a.hook, ev.get("state", "?"), str(ev.get("score", 0)), str(ev.get("blocks", 0))]))
    except KeyboardInterrupt:
        pass


# ------------------------------------------------------------------- live ---
RAMP = [
    ("dim ", "·"), ("grey46 ", "·"), ("blue ", "▂"), ("cyan ", "▄"),
    ("green ", "▆"), ("yellow ", "▆"), ("dark_orange ", "█"), ("red ", "█"),
]


def cell(v: float):
    i = min(len(RAMP) - 1, max(0, int(v)))
    return RAMP[i]


def cmd_live(a):
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    con = Console()
    try:
        sock = socket.create_connection((a.ip, 5515), timeout=5)
    except OSError as e:
        con.print(f"[red]cannot reach motiond telemetry on {a.ip}:5515 — is MOTION=1 and the cam healthy? ({e})[/]")
        sys.exit(1)
    sock.settimeout(3)
    state = {"S": None, "G": None, "n": 0}

    def reader():
        buf = ""
        while True:
            try:
                d = sock.recv(8192)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            if not d:
                return
            buf += d.decode(errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                p = line.split()
                if not p:
                    continue
                if p[0] == "S" and len(p) >= 53:
                    state["S"] = (int(p[1]), int(p[2]), int(p[3]), int(p[4]), [int(x) for x in p[5:53]])
                    state["n"] += 1
                elif p[0] == "G" and len(p) >= 769:
                    state["G"] = [int(x) for x in p[1:769]]

    threading.Thread(target=reader, daemon=True).start()

    def render():
        s = state["S"]
        t = Text()
        if not s:
            t.append("waiting for telemetry...\n")
            return Panel(t, title="motiond live")
        score, act, st, frames, sb = s
        t.append(f"score {score:<8} active {act}/48  state ", style="bold")
        t.append("MOTION" if st else "idle", style="bold red" if st else "bold green")
        t.append(f"   frames={frames}  grid={'yes' if state['G'] else 'wait'}\n\n")
        for r in range(6):
            for c in range(8):
                v = sb[r * 8 + c]
                style, glyph = cell(v / 4000.0 * 7)
                t.append(glyph * 2, style=style)
            t.append("\n")
        g = state["G"]
        if g:
            t.append("\nraw 32x24 ISP 3DNR difference grid:\n", style="dim")
            mx = max(max(g), 1)
            for r in range(24):
                for c in range(32):
                    style, glyph = cell(g[r * 32 + c] / mx * 7)
                    t.append(glyph, style=style)
                t.append("\n")
        return Panel(t, title=f"motiond live — {a.ip}")

    with Live(render(), console=con, refresh_per_second=8) as live:
        last = 0
        while True:
            if state["n"] != last:
                last = state["n"]
                live.update(render())
            time.sleep(0.12)


# ------------------------------------------------------------------- snap ---
def cmd_snap(a):
    out = a.out or f"cam_snap_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
    if ffmpeg_capture(a.ip, out):
        print(f"saved {out}")
        ch = chroma_of(out)
        if ch:
            print(f"chroma UAVG={ch[0]} VAVG={ch[1]}  (128.0/128.0 = grey, ~135 = color)")
    else:
        print("RTSP capture failed", file=sys.stderr)
        sys.exit(1)


# ------------------------------------------------------------------ shell ---
def cmd_shell(a):
    print(f"connecting to no-login shell on {a.ip}:24  (Ctrl-] quits, ^C for prompt)")
    for cmd in (["telnet", a.ip, "24"], ["nc", a.ip, "24"]):
        if shutil.which(cmd[0]):
            os_execvp(cmd)
    print("need telnet or nc", file=sys.stderr)


def os_execvp(cmd):
    import os
    try:
        os.execvp(cmd[0], cmd)
    except OSError:
        pass


# ------------------------------------------------------------------- main ---
def main():
    p = argparse.ArgumentParser(prog="camtool", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", cmd_status), ("shell", cmd_shell)):
        sp = sub.add_parser(name)
        sp.add_argument("ip", nargs="?", default=DEFAULT_IP)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("snap")
    sp.add_argument("ip", nargs="?", default=DEFAULT_IP)
    sp.add_argument("-o", "--out")
    sp.set_defaults(fn=cmd_snap)
    sp = sub.add_parser("events")
    sp.add_argument("--port", type=int, default=5514)
    sp.add_argument("--hook", help="script to run on each event: HOOK state score blocks")
    sp.set_defaults(fn=cmd_events)
    sp = sub.add_parser("live")
    sp.add_argument("ip", nargs="?", default=DEFAULT_IP)
    sp.set_defaults(fn=cmd_live)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
