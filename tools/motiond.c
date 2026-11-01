/* motiond v2 - on-device motion detection for AK3918 cams from the ISP 3DNR stats grid.
 *
 * /dev/isp-stats-3dnr-0 = V4L2 vb2 node (ak_isp.ko) streaming the ISP per-frame
 * 32x24 block temporal-difference (SAD) grid: 128B header + 768 x u16, ~12.5 fps.
 * Static-scene blocks sit ~200-800; a person in frame measures 2000+.
 *
 * Algorithm: average into 6x8 superblocks -> per-superblock integer EMA (learned
 * noise floor) -> superblock active if v > abs-floor AND v > mult*baseline ->
 * sliding-window vote -> start/stop events via UDP broadcast + /tmp/motion.status.
 *
 * usage: motiond [opts]
 *   --abs N      absolute SAD superblock floor   (default 1200)
 *   --mult N     x baseline multiplier           (default 3)
 *   --minb N     active superblocks to trigger   (default 2)
 *   --win N      vote window frames              (default 6)
 *   --need N     motion frames within win        (default 3)
 *   --hold S     min seconds between events      (default 4)
 *   --port N     UDP broadcast port              (default 5514, 0=off)
 *   --ctrl-port N TCP telemetry port for camtool live (default 0=off)
 * writes only to /tmp.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <linux/videodev2.h>

#define SBC 8            /* superblock cols */
#define SBR 6            /* superblock rows */
#define NSB (SBC * SBR)

static const char *DEV = "/dev/isp-stats-3dnr-0";
static int ABS_ = 1200, MULT = 3, MINB = 2, WIN = 6, NEED = 3, HOLD = 4, PORT = 5514, CTRL = 0;

static void *map[4];

/* ---- ctrl socket: stream grid telemetry to one TCP client (PC visualizer) ---- */
static int csock = -1, cclient = -1;
static void ctrl_init(int port) {
    if (!port) return;
    csock = socket(AF_INET, SOCK_STREAM, 0);
    if (csock < 0) return;
    int on = 1;
    setsockopt(csock, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET; a.sin_port = htons(port);
    a.sin_addr.s_addr = INADDR_ANY;
    if (bind(csock, (struct sockaddr *)&a, sizeof a) || listen(csock, 1)) { close(csock); csock = -1; }
    { int fl = fcntl(csock, F_GETFL, 0); fcntl(csock, F_SETFL, fl | O_NONBLOCK); }
}
static void ctrl_accept(void) {
    if (csock < 0 || cclient >= 0) return;
    int c = accept(csock, 0, 0);
    if (c >= 0) cclient = c;
}
static void ctrl_send(const char *buf, int n) {
    if (cclient < 0) return;
    int off = 0;
    while (off < n) {
        int w = send(cclient, buf + off, n - off, MSG_NOSIGNAL);
        if (w <= 0) { close(cclient); cclient = -1; return; }
        off += w;
    }
}

static void event(int on, int score, int blocks, long t) {
    char buf[256];
    int n = snprintf(buf, sizeof buf,
        "{\"ev\":\"motion\",\"state\":\"%s\",\"score\":%d,\"blocks\":%d,\"ts\":%ld}\n",
        on ? "start" : "stop", score, blocks, t);
    FILE *f = fopen("/tmp/motion.status.tmp", "w");   /* atomic swap: readers never see a torn line */
    if (f) { fwrite(buf, 1, n, f); fclose(f); rename("/tmp/motion.status.tmp", "/tmp/motion.status"); }
    if (PORT) {
        int s = socket(AF_INET, SOCK_DGRAM, 0);
        if (s >= 0) {
            int on = 1; setsockopt(s, SOL_SOCKET, SO_BROADCAST, &on, sizeof on);
            struct sockaddr_in a;
            memset(&a, 0, sizeof a);
            a.sin_family = AF_INET; a.sin_port = htons(PORT);
            a.sin_addr.s_addr = INADDR_BROADCAST;
            sendto(s, buf, n, 0, (struct sockaddr *)&a, sizeof a);
            close(s);
        }
    }
    printf("EVENT %s score=%d blocks=%d t=%ld\n", on ? "START" : "STOP ", score, blocks, t);
    fflush(stdout);
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) {
        char *a = argv[i];
        if      (!strcmp(a, "--abs") && i + 1 < argc) ABS_ = atoi(argv[++i]);
        else if (!strcmp(a, "--mult") && i + 1 < argc) MULT = atoi(argv[++i]);
        else if (!strcmp(a, "--minb") && i + 1 < argc) MINB = atoi(argv[++i]);
        else if (!strcmp(a, "--win") && i + 1 < argc) WIN = atoi(argv[++i]);
        else if (!strcmp(a, "--need") && i + 1 < argc) NEED = atoi(argv[++i]);
        else if (!strcmp(a, "--hold") && i + 1 < argc) HOLD = atoi(argv[++i]);
        else if (!strcmp(a, "--port") && i + 1 < argc) PORT = atoi(argv[++i]);
        else if (!strcmp(a, "--ctrl-port") && i + 1 < argc) CTRL = atoi(argv[++i]);
        else { fprintf(stderr, "bad or valueless arg: %s\n", a); return 2; }
    }
    /* hist[] is 64 entries and every divisor feeds % WIN: clamp, never trust */
    if (WIN  < 1 || WIN > 64)  WIN = 6;
    if (NEED < 1 || NEED > WIN) NEED = WIN > 3 ? 3 : WIN;
    if (MINB < 1 || MINB > 48) MINB = 2;
    if (ABS_ < 0)  ABS_ = 0;
    if (MULT < 1)  MULT = 1;
    if (HOLD < 0)  HOLD = 0;
    if (PORT < 0 || PORT > 65535) PORT = 5514;
    if (CTRL < 0 || CTRL > 65535) CTRL = 0;

    int fd = open(DEV, O_RDWR | O_NONBLOCK);
    if (fd < 0) { fprintf(stderr, "open %s: %s\n", DEV, strerror(errno)); return 1; }
    struct v4l2_format f;
    memset(&f, 0, sizeof f);
    f.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(fd, VIDIOC_S_FMT, &f) < 0) { fprintf(stderr, "s_fmt: %s\n", strerror(errno)); return 1; }
    struct v4l2_requestbuffers rb;
    memset(&rb, 0, sizeof rb);
    rb.count = 4; rb.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rb.memory = V4L2_MEMORY_MMAP;
    if (ioctl(fd, VIDIOC_REQBUFS, &rb) < 0) { fprintf(stderr, "reqbufs: %s\n", strerror(errno)); return 1; }
    for (unsigned i = 0; i < rb.count; i++) {
        struct v4l2_buffer b;
        memset(&b, 0, sizeof b);
        b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP; b.index = i;
        if (ioctl(fd, VIDIOC_QUERYBUF, &b) < 0) { fprintf(stderr, "querybuf: %s\n", strerror(errno)); return 1; }
        map[i] = mmap(0, b.length, PROT_READ, MAP_SHARED, fd, b.m.offset);
        if (map[i] == MAP_FAILED) { fprintf(stderr, "mmap: %s\n", strerror(errno)); return 1; }
        ioctl(fd, VIDIOC_QBUF, &b);
    }
    int mt = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(fd, VIDIOC_STREAMON, &mt) < 0) { fprintf(stderr, "streamon: %s\n", strerror(errno)); return 1; }
    ctrl_init(CTRL);

    static int sb[NSB], bg[NSB];
    int hist[64], hi = 0, hn = 0, state = 0, have_bg = 0;
    long t_ev = 0, t_log = 0, frames = 0;
    printf("motiond v2: dev=%s abs=%d mult=%d minb=%d win=%d need=%d port=%d\n",
           DEV, ABS_, MULT, MINB, WIN, NEED, PORT);
    fflush(stdout);

    for (;;) {
        struct v4l2_buffer b;
        fd_set rs; FD_ZERO(&rs); FD_SET(fd, &rs);
        struct timeval tv = { 2, 0 };
        if (select(fd + 1, &rs, 0, 0, &tv) <= 0) continue;
        memset(&b, 0, sizeof b);
        b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP;
        if (ioctl(fd, VIDIOC_DQBUF, &b) < 0) { usleep(50000); continue; }
        unsigned short *g = (unsigned short *)((char *)map[b.index] + 128);
        int nsb_bytes = (int)b.bytesused - 128;
        if (nsb_bytes < 768 * 2) { ioctl(fd, VIDIOC_QBUF, &b); continue; }
        /* superblock averages over 4x4 blocks */
        for (int r = 0; r < SBR; r++)
            for (int c = 0; c < SBC; c++) {
                long s = 0;
                for (int rr = r * 4; rr < r * 4 + 4; rr++)
                    for (int cc = c * 4; cc < c * 4 + 4; cc++) s += g[rr * 32 + cc];
                sb[r * SBC + c] = (int)(s / 16);
            }
        ioctl(fd, VIDIOC_QBUF, &b);
        frames++;
        long t = time(NULL);
        if (!have_bg) { memcpy(bg, sb, sizeof sb); have_bg = 1; continue; }

        int act = 0, score = 0;
        for (int k = 0; k < NSB; k++) {
            int base = bg[k];
            int th = ABS_ > base * MULT ? ABS_ : base * MULT;
            if (sb[k] > th) { act++; score += sb[k] - th; }
            else bg[k] += (sb[k] - bg[k]) / 16;     /* frozen while active */
        }
        /* telemetry for PC visualizer: S-line every frame, G-line (full grid) every 4th */
        ctrl_accept();
        if (cclient >= 0) {
            char tbuf[600];
            int tn = snprintf(tbuf, sizeof tbuf, "S %d %d %d %ld", score, act, state, frames);
            for (int k = 0; k < NSB && tn < (int)sizeof tbuf - 8; k++)
                tn += snprintf(tbuf + tn, sizeof tbuf - tn, " %d", sb[k]);
            snprintf(tbuf + tn, sizeof tbuf - tn, "\n");
            ctrl_send(tbuf, strlen(tbuf));
            if (frames % 4 == 0) {
                char gbuf[6200];
                int gn = snprintf(gbuf, sizeof gbuf, "G");
                for (int k = 0; k < 768 && gn < (int)sizeof gbuf - 8; k++)
                    gn += snprintf(gbuf + gn, sizeof gbuf - gn, " %u", g[k]);
                snprintf(gbuf + gn, sizeof gbuf - gn, "\n");
                ctrl_send(gbuf, strlen(gbuf));
            }
        }
        hist[hi] = act >= MINB; hi = (hi + 1) % WIN; if (hn < WIN) hn++;
        int votes = 0;
        for (int i = 0; i < hn; i++) votes += hist[i];

        if (!state && votes >= NEED && t - t_ev >= HOLD) {
            state = 1; t_ev = t; event(1, score, act, t);
        } else if (state && !votes && t - t_ev >= HOLD) {
            state = 0; t_ev = t; event(0, score, act, t);
        }
        if (t - t_log >= 2) {
            t_log = t;
            printf("score=%-7d act=%d/%d votes=%d/%d st=%d f=%ld\n", score, act, NSB, votes, hn, state, frames);
            fflush(stdout);
        }
    }
}
