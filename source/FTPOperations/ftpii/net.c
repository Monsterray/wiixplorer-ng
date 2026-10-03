#include "network/TransferSocket.h"
/*

Copyright (C) 2008 Joseph Jordan <joe.ftpii@psychlaw.com.au>

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from
the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

1.The origin of this software must not be misrepresented; you must not
claim that you wrote the original software. If you use this software in a
product, an acknowledgment in the product documentation would be
appreciated but is not required.

2.Altered source versions must be plainly marked as such, and must not be
misrepresented as being the original software.

3.This notice may not be removed or altered from any source distribution.

*/
#include <errno.h>
#include <gccore.h>
#include <network.h>
#include <stdio.h>
#include <string.h>
#include <malloc.h>
#include <unistd.h>
#include <sys/fcntl.h>

#include "Tools/gxprintf.h"
#include "net.h"

#define MAX_NET_BUFFER_SIZE (60*1024)
#define MIN_NET_BUFFER_SIZE 4096
#define FREAD_BUFFER_SIZE (60*1024)

static u32 NET_BUFFER_SIZE = MAX_NET_BUFFER_SIZE;
/* The retained comparison backend must also release its scratch arena. */
static char *transfer_buffer;
s32 init_ftp_buffers(void) {
    if (!transfer_buffer) transfer_buffer = (char *)memalign(32, MAX_NET_BUFFER_SIZE);
    return transfer_buffer ? 0 : -ENOMEM;
}
void cleanup_ftp_buffers(void) {
    free(transfer_buffer); transfer_buffer = NULL;
    NET_BUFFER_SIZE = MAX_NET_BUFFER_SIZE;
}

#if 0
void initialise_network() {
	printf("Waiting for network to initialise...\n");
	s32 result = -1;
	while (!check_reset_synchronous() && result < 0) {
		net_deinit();
		while (!check_reset_synchronous() && (result = net_init()) == -EAGAIN);
		if (result < 0) printf("net_init() failed: [%i] %s, retrying...\n", result, strerror(-result));
	}
	if (result >= 0) {
		u32 ip = 0;
		do {
			ip = net_gethostip();
			if (!ip) printf("net_gethostip() failed, retrying...\n");
		} while (!check_reset_synchronous() && !ip);
		if (ip) {
			struct in_addr addr;
			addr.s_addr = ip;
			printf("Network initialised.  Wii IP address: %s\n", inet_ntoa(addr));
		}
	}
}
#endif

s32 set_blocking(s32 s, bool blocking) {
	s32 flags;
	flags = net_fcntl(s, F_GETFL, 0);
	if (flags >= 0) flags = net_fcntl(s, F_SETFL, blocking ? (flags&~4) : (flags|4));
	return flags;
}

s32 net_close_blocking(s32 s) {
	set_blocking(s, true);
	return net_close(s);
}

s32 create_server(u16 port) {
	s32 server = net_socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
	if (server < 0) return server;
    s32 mode = set_blocking(server, false);
    if (mode < 0) { net_close(server); return mode; }

	struct sockaddr_in bindAddress;
	memset(&bindAddress, 0, sizeof(bindAddress));
	bindAddress.sin_family = AF_INET;
	bindAddress.sin_len = sizeof(bindAddress);
	bindAddress.sin_port = htons(port);
	bindAddress.sin_addr.s_addr = net_gethostip();

	s32 ret;
	if ((ret = net_bind(server, (struct sockaddr *)&bindAddress, sizeof(bindAddress))) < 0) {
		net_close(server);
		gxprintf("Error binding socket: [%i] %s\n", -ret, strerror(-ret));
		return ret;
	}
	if ((ret = net_listen(server, 3)) < 0) {
		net_close(server);
		gxprintf("Error listening on socket: [%i] %s\n", -ret, strerror(-ret));
		return ret;
	}

	return server;
}

static s32 transfer_exact(s32 s, char *buf, s32 length) {
	s32 result = 0;
	s32 remaining = length;
	s32 bytes_transferred;
	while (remaining) {
		try_again_with_smaller_buffer:
		bytes_transferred = wx_transfer_write(s, buf, MIN(remaining, (int) NET_BUFFER_SIZE));
		if (bytes_transferred > 0) {
			remaining -= bytes_transferred;
			buf += bytes_transferred;
		} else if (bytes_transferred < 0) {
			if (bytes_transferred == -EINVAL && NET_BUFFER_SIZE == MAX_NET_BUFFER_SIZE) {
				NET_BUFFER_SIZE = MIN_NET_BUFFER_SIZE;
				usleep(100);
				goto try_again_with_smaller_buffer;
			}
			result = bytes_transferred;
			break;
		} else {
			result = -ENODATA;
			break;
		}
	}
	set_blocking(s, false);
	return result;
}

s32 send_exact(s32 s, char *buf, s32 length) {
	return transfer_exact(s, buf, length);
}

s32 send_from_file(s32 s, FILE *f) {
	/* Callbacks run serially on the single FTP server thread. */
	if (!transfer_buffer) return -ENOMEM;
    char *buf = transfer_buffer;

	s32 bytes_read;
	s32 result = 0;

	bytes_read = fread(buf, 1, FREAD_BUFFER_SIZE, f);
	if (bytes_read > 0) {
		result = send_exact(s, buf, bytes_read);
		if (result < 0) goto end;
	}
	if (bytes_read < FREAD_BUFFER_SIZE) {
		result = ferror(f) || !feof(f) ? -EIO : 0;
		goto end;
	}
	return bytes_read;
	end:
	return result;
}

s32 recv_to_file(s32 s, FILE *f) {
    if (!transfer_buffer) return -ENOMEM;
    char *buf = transfer_buffer;
    s32 bytes_read = net_read(s, buf, MIN(NET_BUFFER_SIZE, 16384));
    if (bytes_read <= 0) return bytes_read;
    if (fwrite(buf, 1, bytes_read, f) != (size_t)bytes_read) return -EIO;
    // Yield to the other clients after one chunk; positive means progress.
    return bytes_read;
}
