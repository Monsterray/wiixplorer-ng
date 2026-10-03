/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef WX_FTPSRV_CONFIG_H
#define WX_FTPSRV_CONFIG_H
#define FTPSRV_VERSION_STR "1.2.2-wiixplorer"
#define FTP_MAX_SESSIONS 4
#define FTP_FILE_BUFFER_SIZE (32 * 1024)
#define FTP_SEND_BLOCK_SIZE 4096
#define FTP_PATHNAME_SIZE 1024
#define FTP_VFS_HEADER "../WiiXplorerFtpVfs.h"
#define FTP_SOCKET_HEADER "../WiiXplorerFtpSocket.h"
#define HAVE_STRNCASECMP 1
#define HAVE_LOCALTIME_R 1
#define HAVE_GMTIME_R 1
#include <strings.h>
#endif
