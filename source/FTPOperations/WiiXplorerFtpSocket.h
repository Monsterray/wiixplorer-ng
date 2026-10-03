/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef WX_FTP_SOCKET_H
#define WX_FTP_SOCKET_H
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#ifdef GEKKO
#include <network.h>
#include <ogc/ipc.h>
#include <ogc/lwp_watchdog.h>
extern int wx_ftp_stopping(void);
#define WX_NET(fn) net_##fn
static inline int wx_sock_result(int rc) { if (rc < 0) { errno = -rc; return -1; } return rc; }
#else
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <unistd.h>
#define WX_NET(fn) fn
static inline int wx_sock_result(int rc) { return rc; }
#endif
struct FtpSocket { int s; int valid; int listening; int emulated; };
struct FtpSocketPollFd {
#ifdef GEKKO
    struct pollsd s;
#else
    struct pollfd s;
#endif
};
static inline int ftp_socket_close_wx(struct FtpSocket *s) {
    if (s->valid) {
        /* Do not shut down a queued download with SHUT_RDWR: IOS may reset it. */
        wx_sock_result(WX_NET(shutdown)(s->s, 1));
#ifdef GEKKO
        /* HBC-Reborn's hardware-tested close rule: allow queued bytes to drain.
         * Disable/shutdown skips this wait and tears down all sockets at once. */
        if (!s->listening && !wx_ftp_stopping()) {
            int mode = net_fcntl(s->s,F_GETFL,0);
            if (mode >= 0 && net_fcntl(s->s,F_SETFL,mode|4) >= 0) {
                u64 until = gettime()+secs_to_ticks(1);
                while (!wx_ftp_stopping() && gettime() < until) {
                    char discard[64];
                    int n = net_recv(s->s,discard,sizeof(discard),0);
                    if (!n || (n < 0 && n != -EAGAIN && n != -EINTR)) break;
                    struct pollsd ready = {s->s,0x0003,0};
                    if (net_poll(&ready,1,10) < 0) break;
                }
            }
        }
#endif
        wx_sock_result(WX_NET(close)(s->s));
    }
    memset(s, 0, sizeof(*s)); return 0;
}
static inline int ftp_socket_set_nonblocking_enable_wx(struct FtpSocket *s, int enable) {
    int flags = wx_sock_result(WX_NET(fcntl)(s->s,F_GETFL,0));
#ifdef GEKKO
    const int bit = 4; /* official libogc IOS flag; newlib O_NONBLOCK differs */
#else
    const int bit = O_NONBLOCK;
#endif
    return flags < 0 ? -1 : wx_sock_result(WX_NET(fcntl)(s->s,F_SETFL,enable ? flags|bit : flags&~bit));
}
static inline int wx_sock_prepare(struct FtpSocket *s, int rc) {
    if (wx_sock_result(rc) < 0) { memset(s,0,sizeof(*s)); return -1; }
    s->s = rc; s->valid = 1; s->listening = 0; s->emulated = 0;
    if (ftp_socket_set_nonblocking_enable_wx(s,1) < 0) { ftp_socket_close_wx(s); return -1; }
#ifdef GEKKO
    unsigned capacity = 4096;
    if (net_setsockopt(s->s,SOL_SOCKET,SO_SNDLOWAT,&capacity,sizeof(capacity)) < 0) {
        int d = IOS_Open("/dev/dolphin",0);
        if (d < 0) { ftp_socket_close_wx(s); errno = ENOTSUP; return -1; }
        IOS_Close(d); s->emulated = 1;
    }
#endif
    return rc;
}
static inline int ftp_socket_open_wx(struct FtpSocket *s,int domain,int type,int protocol) {
    return wx_sock_prepare(s,WX_NET(socket)(domain,type,protocol));
}
static inline int ftp_socket_accept_wx(struct FtpSocket *s,struct FtpSocket *listener,struct sockaddr *addr,size_t *length) {
    socklen_t len = *length;
    int rc = WX_NET(accept)(listener->s,addr,&len); *length = len;
    return wx_sock_prepare(s,rc);
}
static inline int ftp_socket_recv_wx(struct FtpSocket *s,void *buf,size_t size,int flags) {
    if (size > 16384) size = 16384;
    return wx_sock_result(WX_NET(recv)(s->s,buf,size,flags));
}
static inline int ftp_socket_send_wx(struct FtpSocket *s,const void *buf,size_t size,int flags) {
#ifdef GEKKO
    if (size > 4096) size = 4096;
    if (!s->emulated) {
        struct pollsd ready = {s->s,0x0008,0};
        int rc = wx_sock_result(net_poll(&ready,1,0));
        if (rc < 0) return -1;
        if (ready.revents & 0x0060) { errno = ECONNRESET; return -1; }
        if (!(ready.revents & 0x0008)) { errno = EAGAIN; return -1; }
        int original = wx_sock_result(net_fcntl(s->s,F_GETFL,0));
        if (original < 0 || wx_sock_result(net_fcntl(s->s,F_SETFL,original&~4)) < 0) return -1;
        rc = wx_sock_result(net_send(s->s,buf,size,flags));
        int saved = errno;
        if (wx_sock_result(net_fcntl(s->s,F_SETFL,original)) < 0) return -1;
        errno = saved; return rc;
    }
#endif
    return wx_sock_result(WX_NET(send)(s->s,buf,size,flags));
}
static inline int ftp_socket_bind_wx(struct FtpSocket *s,struct sockaddr *a,size_t n) {
#ifdef GEKKO
    a->sa_len = n;
#endif
    return wx_sock_result(WX_NET(bind)(s->s,a,n));
}
static inline int ftp_socket_connect_wx(struct FtpSocket *s,struct sockaddr *a,size_t n) {
#ifdef GEKKO
    a->sa_len = n;
#endif
    return wx_sock_result(WX_NET(connect)(s->s,a,n));
}
static inline int ftp_socket_listen_wx(struct FtpSocket *s,int backlog) {
    int rc = wx_sock_result(WX_NET(listen)(s->s,backlog));
    if (!rc) s->listening = 1;
    return rc;
}
static inline int ftp_socket_getsockname_wx(struct FtpSocket *s,struct sockaddr *a,size_t *n) {
    socklen_t len = *n; int rc = wx_sock_result(WX_NET(getsockname)(s->s,a,&len)); *n = len; return rc;
}
static inline int ftp_socket_set_reuseaddr_enable_wx(struct FtpSocket *s,int enable) {
    return wx_sock_result(WX_NET(setsockopt)(s->s,SOL_SOCKET,SO_REUSEADDR,&enable,sizeof(enable)));
}
/* No speculative socket tuning: IOS support differs from host sockets. */
static inline int ftp_socket_set_nodelay_enable_wx(struct FtpSocket *s,int enable) { (void)s;(void)enable;return 0; }
static inline int ftp_socket_set_keepalive_enable_wx(struct FtpSocket *s,int enable) { (void)s;(void)enable;return 0; }
static inline int ftp_socket_set_throughput_enable_wx(struct FtpSocket *s,int enable) { (void)s;(void)enable;return 0; }
static inline int ftp_socket_poll_wx(struct FtpSocketPollEntry *entries,struct FtpSocketPollFd *fds,size_t count,int timeout) {
    for (size_t i=0;i<count;++i) {
        fds[i].s.revents = 0; fds[i].s.events = 0; entries[i].revents = (enum FtpSocketPollType)0;
        struct FtpSocket *s = entries[i].fd;
#ifdef GEKKO
        fds[i].s.socket = s && s->valid ? s->s : -1;
        if (entries[i].events & FtpSocketPollType_IN) fds[i].s.events |= 0x0003;
        if (entries[i].events & FtpSocketPollType_OUT) fds[i].s.events |= 0x0008;
#else
        fds[i].s.fd = s && s->valid ? s->s : -1;
        if (entries[i].events & FtpSocketPollType_IN) fds[i].s.events |= POLLIN;
        if (entries[i].events & FtpSocketPollType_OUT) fds[i].s.events |= POLLOUT;
#endif
    }
#ifdef GEKKO
    int rc = wx_sock_result(net_poll((struct pollsd *)fds,count,timeout));
#else
    int rc = poll((struct pollfd *)fds,count,timeout);
#endif
    if (rc < 0) return rc;
    for (size_t i=0;i<count;++i) {
        unsigned events = 0;
#ifdef GEKKO
        if (fds[i].s.revents & 0x0003) events |= FtpSocketPollType_IN;
        if (fds[i].s.revents & 0x0008) events |= FtpSocketPollType_OUT;
        if (fds[i].s.revents & 0x0020) events |= FtpSocketPollType_ERROR;
        if (fds[i].s.revents & 0x0040) events |= (entries[i].events & FtpSocketPollType_IN) ? FtpSocketPollType_IN : FtpSocketPollType_ERROR;
        /* IOS can omit readiness for listening sockets. Accept is nonblocking. */
        if (entries[i].fd && entries[i].fd->valid && entries[i].fd->listening) events |= FtpSocketPollType_IN;
#else
        if (fds[i].s.revents & POLLIN) events |= FtpSocketPollType_IN;
        if (fds[i].s.revents & POLLOUT) events |= FtpSocketPollType_OUT;
        if (fds[i].s.revents & (POLLERR|POLLNVAL)) events |= FtpSocketPollType_ERROR;
        if (fds[i].s.revents & POLLHUP) events |= FtpSocketPollType_IN; /* consume EOF */
#endif
        entries[i].revents = (enum FtpSocketPollType)events;
    }
    return rc;
}
#define ftp_socket_open ftp_socket_open_wx
#define ftp_socket_recv ftp_socket_recv_wx
#define ftp_socket_send ftp_socket_send_wx
#define ftp_socket_close ftp_socket_close_wx
#define ftp_socket_accept ftp_socket_accept_wx
#define ftp_socket_bind ftp_socket_bind_wx
#define ftp_socket_connect ftp_socket_connect_wx
#define ftp_socket_listen ftp_socket_listen_wx
#define ftp_socket_getsockname ftp_socket_getsockname_wx
#define ftp_socket_set_reuseaddr_enable ftp_socket_set_reuseaddr_enable_wx
#define ftp_socket_set_nodelay_enable ftp_socket_set_nodelay_enable_wx
#define ftp_socket_set_keepalive_enable ftp_socket_set_keepalive_enable_wx
#define ftp_socket_set_throughput_enable ftp_socket_set_throughput_enable_wx
#define ftp_socket_set_nonblocking_enable ftp_socket_set_nonblocking_enable_wx
#define ftp_socket_poll ftp_socket_poll_wx
#endif
