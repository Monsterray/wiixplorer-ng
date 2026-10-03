#ifndef WX_TRANSFER_SOCKET_H
#define WX_TRANSFER_SOCKET_H
#include <gctypes.h>
#ifdef __cplusplus
extern "C" {
#endif
int wx_transfer_cancelled(void);
u64 wx_transfer_deadline(u32 seconds);
int wx_transfer_expired(u64 deadline);
/* Blocking IOS sends are required for correctness on real Wii hardware.
 * Poll for a full 4 KiB send window: 10 seconds idle, 120 seconds per batch. */
/* Returns bytes written (up to 256 KiB) or a negative failure. */
s32 wx_transfer_write(s32 socket, const void *data, u32 length);
/* One nonblocking receive, with a 10 second deadline and exit cancellation. */
s32 wx_transfer_read(s32 socket, void *data, u32 length);
#ifdef __cplusplus
}
#endif
#endif
