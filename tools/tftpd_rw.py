#!/usr/bin/env python3
"""tftpd_rw - minimal TFTP server (read+write, octet mode) for the dev loop.
PC:  python3 tftpd_rw.py <dir> <port>                          (default . 6970)
cam: tftp -g -r hello -l /tmp/hello <pc-ip> 6970               # push to cam
     tftp -p -l /usr/local/isp_gc20c3.conf -r f.bin <pc-ip> 6970  # pull
Each transfer runs on its own thread with its own UDP port (RFC 1350 TID): a
dead client stalls only its own transfer, never the server. Every completed
transfer logs its sha1; verify with sha1sum on the cam. WRQ writes land as
*.part and are renamed only when complete - a truncated file never carries
the final name. Dev tool: WRQ = unauthenticated writes into <dir>; run on a
LAN you own."""
import hashlib, os, socket, stat, struct, sys, threading

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6970
BLK, TIMEOUT, RETRIES = 512, 5.0, 5

srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
srv.bind(("0.0.0.0", PORT))
print(f"serving(rw) {ROOT} on udp/{PORT}", flush=True)

def msg(op, n):
    return struct.pack("!HH", op, n & 0xFFFF)

def err(to, code, text):
    try:
        srv.sendto(struct.pack("!HH", 5, code) + text.encode() + b"\0", to)
    except OSError:
        pass

def tid():
    ts = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ts.bind(("0.0.0.0", 0))          # per-transfer TID; clients follow it
    ts.settimeout(TIMEOUT)
    return ts

def send_file(path, addr):
    ip = addr[0]
    try:
        with open(path, "rb") as f, tid() as ts:
            h, size, blk = hashlib.sha1(), 0, 1
            while True:
                chunk = f.read(BLK)  # forward-only; short/empty block ends file
                h.update(chunk)
                size += len(chunk)
                acked = False
                for _ in range(RETRIES):
                    ts.sendto(msg(3, blk) + chunk, addr)
                    try:
                        pkt, a2 = ts.recvfrom(2048)
                    except OSError:
                        continue     # timeout counts against RETRIES
                    if (a2[0] == ip and len(pkt) >= 4
                            and struct.unpack("!HH", pkt[:4]) == (4, blk & 0xFFFF)):
                        acked = True
                        break
                if not acked:
                    print(f"  get {path}: aborted at block {blk}", flush=True)
                    return
                if len(chunk) < BLK:
                    print(f"  sent {size} B sha1 {h.hexdigest()}", flush=True)
                    return
                blk += 1
    except OSError as e:
        print("  get error:", e, flush=True)

def recv_file(path, addr):
    ip = addr[0]
    ts = tid()
    part = f"{path}.{ts.getsockname()[1]}.part"
    try:
        with ts, open(part, "wb") as f:
            ts.sendto(msg(4, 0), addr)          # open succeeded -> ACK0
            h = hashlib.sha1()
            expect, last_acked, idle = 1, 0, 0
            while True:
                try:
                    pkt, a2 = ts.recvfrom(2048)
                except OSError:
                    pkt, a2 = None, None
                if pkt is None or a2[0] != ip or len(pkt) < 4:
                    idle += 1                   # timeout or junk: bounded
                    if idle >= RETRIES:
                        print(f"  put {path}: aborted (client gone)", flush=True)
                        return
                    if pkt is None:             # unstick a client that lost our ack
                        ts.sendto(msg(4, last_acked), addr)
                    continue
                o, blk = struct.unpack("!HH", pkt[:4])
                if o == 5:
                    print("  client error:",
                          pkt[4:].split(b"\0")[0].decode("latin1", "replace"), flush=True)
                    return
                if o == 2:                      # duplicated WRQ -> restart, RFC 1350
                    f.seek(0); f.truncate()
                    h = hashlib.sha1()
                    expect, last_acked, idle = 1, 0, 0
                    ts.sendto(msg(4, 0), addr)
                    continue
                if o != 3:
                    continue
                if blk != expect:               # duplicate/late DATA: re-ack only
                    ts.sendto(msg(4, last_acked), addr)
                    continue
                data = pkt[4:]
                f.write(data)
                f.flush()
                h.update(data)
                ts.sendto(msg(4, blk), addr)
                expect, last_acked, idle = (expect + 1) & 0xFFFF, blk, 0
                if len(data) < BLK:
                    os.fsync(f.fileno())
                    break
            os.replace(part, path)              # atomic: full file or none
            print(f"  wrote {os.path.getsize(path)} B sha1 {h.hexdigest()}", flush=True)
    except OSError as e:
        err(addr, 3, "could not store file")
        print("  put error:", e, flush=True)
    finally:
        try:                                    # abort leftovers never keep the name
            if os.path.exists(part):
                os.unlink(part)
        except OSError:
            pass

def jail(name):
    p = os.path.normpath(name)
    if not p or os.path.isabs(p) or ".." in p.split(os.sep):
        return None
    full = os.path.join(ROOT, p)
    return full if full == ROOT or full.startswith(ROOT + os.sep) else None

def handle(pkt, addr):
    if len(pkt) < 4:
        return
    op = struct.unpack("!H", pkt[:2])[0]        # 1 RRQ / 2 WRQ
    if op not in (1, 2):
        if op in (3, 4):                        # stray DATA/ACK: RFC 1350 §4.
            err(addr, 0, "invalid transfer")    # never reply to ERROR (5): loops
        return
    name = pkt[2:].split(b"\0")[0].decode("latin1", "replace")
    path = jail(name)
    if path is None:
        err(addr, 2, "access violation")
        return
    if op == 1:
        try:
            st = os.lstat(path)                 # lstat: no symlink jailbreaks
        except OSError:
            err(addr, 1, "file not found")
            return
        if not stat.S_ISREG(st.st_mode):
            err(addr, 2, "not a regular file")
            return
        print("get", name, "by", addr, flush=True)
        threading.Thread(target=send_file, args=(path, addr), daemon=True).start()
    else:
        try:                            # refuse to replace dirs/symlinks early
            if not stat.S_ISREG(os.lstat(path).st_mode):
                err(addr, 2, "not a regular file")
                return
        except FileNotFoundError:
            pass
        print("put", name, "from", addr, flush=True)
        threading.Thread(target=recv_file, args=(path, addr), daemon=True).start()

try:
    while True:
        try:
            pkt, addr = srv.recvfrom(2048)
        except OSError:
            continue
        try:
            handle(pkt, addr)
        except Exception as e:                  # junk must never kill the loop
            print("dropped:", type(e).__name__, e, flush=True)
except KeyboardInterrupt:
    pass
