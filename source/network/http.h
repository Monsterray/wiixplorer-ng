#ifndef _HTTP_H_
#define _HTTP_H_

#include <errno.h>
#include <ogcsys.h>
#include <stdarg.h>
#include <string.h>

#ifdef __cplusplus
extern "C"
{
#endif

#include "dns.h"

/**
 * A simple structure to keep track of the size of a malloc()ated block of memory
 */
struct block
{
	u32 size;
	unsigned char *data;
};

extern const struct block emptyblock;

struct block downloadfile(const char *url);
s32 GetConnection(char * domain);
struct http_reader {
    int connection;
    u8 pending[4096];
    u32 offset, count;
    u64 deadline;
};
int network_request(struct http_reader *reader, int connection, const char *request, char *filename);
int http_read(struct http_reader *reader, u8 *buf, u32 len);
int network_read(int connection, u8 *buf, u32 len);

#ifdef __cplusplus
}
#endif

#endif /* _HTTP_H_ */
