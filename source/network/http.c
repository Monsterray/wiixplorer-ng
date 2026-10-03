#include "Diagnostics/Probes.h"
#include "http.h"
#include "TransferSocket.h"
#include <ctype.h>
#include <fcntl.h>

/**
 * Emptyblock is a statically defined variable for functions to return if they are unable
 * to complete a request
 */
const struct block emptyblock = {0, NULL};

//The maximum amount of bytes to send per net_write() call
#define NET_BUFFER_SIZE 1024

// Write our message to the server
static s32 send_message(s32 server, char *msg) {
	WX_PROBE(NETWORK, 1, 1);
	WX_PROBE(NETWORK, 3, strlen(msg));
	s32 bytes_transferred = 0;
	s32 remaining = strlen(msg);
	while (remaining) {
		if ((bytes_transferred = wx_transfer_write(server, msg, remaining > NET_BUFFER_SIZE ? NET_BUFFER_SIZE : remaining)) > 0) {
			WX_PROBE(NETWORK, 2, bytes_transferred);
			remaining -= bytes_transferred;
			msg += bytes_transferred;
		} else if (bytes_transferred < 0) {
			return bytes_transferred;
		} else {
			return -ENODATA;
		}
	}
	return 0;
}

/**
 * Connect to a remote server via TCP on a specified port
 *
 * @param u32 ip address of the server to connect to
 * @param u32 the port to connect to on the server
 * @return s32 The connection to the server (negative number if connection could not be established)
 */
static s32 server_connect(u32 ipaddress, u32 socket_port) {
	//Initialize socket
	s32 connection = net_socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
	if (connection < 0) return connection;

	struct sockaddr_in connect_addr;
	memset(&connect_addr, 0, sizeof(connect_addr));
	connect_addr.sin_family = AF_INET;
	connect_addr.sin_port = socket_port;
	connect_addr.sin_addr.s_addr= ipaddress;

	//Attemt to open the socket
	s32 flags = net_fcntl(connection, F_GETFL, 0);
    if (flags < 0 || net_fcntl(connection, F_SETFL, flags | 4) < 0) {
        net_close(connection); return -1;
    }
    u64 deadline = wx_transfer_deadline(10);
    for (;;) {
        s32 result = net_connect(connection, (struct sockaddr*)&connect_addr, sizeof(connect_addr));
        if (result >= 0 || result == -EISCONN) break;
        if ((result != -EINPROGRESS && result != -EALREADY && result != -EAGAIN) ||
            wx_transfer_expired(deadline)) { net_close(connection); return -1; }
        struct pollsd p = {connection, 0x0008, 0};
        if (net_poll(&p, 1, 100) < 0) usleep(1000);
    }
	return connection;
}

//The amount of memory in bytes reserved initially to store the HTTP response in
//Be careful in increasing this number, reading from a socket on the Wii
//will fail if you request more than 20k or so
#define HTTP_BUFFER_SIZE 1024 * 5

//The amount of memory the buffer should expanded with if the buffer is full
#define HTTP_BUFFER_GROWTH 1024 * 5

/**
 * This function reads all the data from a connection into a buffer which it returns.
 * It will return an empty buffer if something doesn't go as planned
 *
 * @param s32 connection The connection identifier to suck the response out of
 * @return block A 'block' struct (see http.h) in which the buffer is located
 */
struct block read_message(s32 connection)
{
	//Create a block of memory to put in the response
	struct block buffer;
	buffer.data = malloc(HTTP_BUFFER_SIZE);
	buffer.size = HTTP_BUFFER_SIZE;

	if(buffer.data == NULL) {
		return emptyblock;
	}

	//The offset variable always points to the first byte of memory that is free in the buffer
	u32 offset = 0;
	u64 deadline = wx_transfer_deadline(60);

	while(1)
	{
		if (wx_transfer_expired(deadline)) { free(buffer.data); return emptyblock; }
		//Fill the buffer with a new batch of bytes from the connection,
		//starting from where we left of in the buffer till the end of the buffer
		s32 bytes_read = wx_transfer_read(connection, buffer.data + offset, buffer.size - offset);

		//Anything below 0 is an error in the connection
		if(bytes_read < 0)
		{
			free(buffer.data);
			return emptyblock;
		}

		//No more bytes were read into the buffer,
		//we assume this means the HTTP response is done
		if(bytes_read == 0)
		{
			break;
		}

		offset += bytes_read;

		//Check if we have enough buffer left over,
		//if not expand it with an additional HTTP_BUFFER_GROWTH worth of bytes
		if(offset >= buffer.size)
		{
			if (buffer.size >= 4*1024*1024) { free(buffer.data); return emptyblock; }
			u32 capacity = buffer.size * 2;
			if (capacity > 4*1024*1024) capacity = 4*1024*1024;
			unsigned char *grown = realloc(buffer.data, capacity);
			if(grown == NULL)
			{
				free(buffer.data);
				return emptyblock;
			}
			buffer.data = grown;
			buffer.size = capacity;
		}
	}

	//At the end of above loop offset should be precisely the amount of bytes that were read from the connection
	buffer.size = offset;

	//Shrink the size of the buffer so the data fits exactly in it
	if(buffer.size == 0) {
		free(buffer.data);
		return emptyblock;
	}
	unsigned char *shrunk = realloc(buffer.data, buffer.size);
	if(shrunk)
		buffer.data = shrunk;

	return buffer;
}

/**
 * Downloads the contents of a URL to memory
 * This method is not threadsafe (because networking is not threadsafe on the Wii)
 */
struct block downloadfile(const char *url)
{
	//Check if the url starts with "http://", if not it is not considered a valid url
	if(!url || strlen(url) > 2048 || strpbrk(url, "\r\n") || strncmp(url, "http://", strlen("http://")) != 0)
	{
		//printf("URL '%s' doesn't start with 'http://'\n", url);
		return emptyblock;
	}

	//Locate the path part of the url by searching for '/' past "http://"
	char *path = strchr(url + strlen("http://"), '/');

	//At the very least the url has to end with '/', ending with just a domain is invalid
	if(path == NULL)
	{
		//printf("URL '%s' has no PATH part\n", url);
		return emptyblock;
	}

	//Extract the domain part out of the url
	int domainlength = path - url - strlen("http://");

	if(domainlength <= 0 || domainlength > 253)
	{
		//printf("No domain part in URL '%s'\n", url);
		return emptyblock;
	}

	char domain[domainlength + 1];
	strncpy(domain, url + strlen("http://"), domainlength);
	domain[domainlength] = '\0';

	//Parsing of the URL is done, start making an actual connection
	u32 ipaddress = getipbynamecached(domain);

	if(ipaddress == 0)
	{
		//printf("\ndomain %s could not be resolved", domain);
		return emptyblock;
	}


	s32 connection = server_connect(ipaddress, 80);

	if(connection < 0) {
		//printf("Error establishing connection");
		return emptyblock;
	}

	//Form a nice request header to send to the webserver
	char* headerformat = "GET %s HTTP/1.0\r\nHost: %s\r\nReferer: %s\r\nUser-Agent: WiiXplorer\r\n\r\n";
	char header[strlen(headerformat) + strlen(path) + strlen(domain)*2 + 1];
	sprintf(header, headerformat, path, domain, domain);

	//Do the request and get the response
    struct http_reader reader;
    int length = network_request(&reader, connection, header, NULL);
    if (length <= 0 || length > 4*1024*1024) { net_close(connection); return emptyblock; }
    struct block file = {(u32)length, malloc(length)};
    if (!file.data) { net_close(connection); return emptyblock; }
    u32 done = 0;
    while (done < file.size) {
        s32 got = http_read(&reader, file.data+done, file.size-done);
        if (got <= 0) break;
        done += got;
    }
    net_close(connection);
    if (done != file.size) { free(file.data); return emptyblock; }
    return file;
}

s32 GetConnection(char * domain)
{
	if(!domain)
		return -1;

	u32 ipaddress = getipbynamecached(domain);
	if(ipaddress == 0)
		return -1;
	s32 connection = server_connect(ipaddress, 80);
	return connection;

}

int network_request(struct http_reader *reader, int connection, const char *request, char *filename)
{
    char *buf = (char *)reader->pending;
    memset(reader, 0, sizeof(*reader));
    reader->connection = connection;
    reader->deadline = wx_transfer_deadline(3600);
    if (filename) filename[0] = 0;
    if (send_message(connection, (char *)request) < 0) return -1;
    u64 header_deadline = wx_transfer_deadline(10);
    char *end;
    for (;;) {
        if (wx_transfer_expired(header_deadline) || reader->count >= sizeof(reader->pending)-1) return -1;
        s32 got = wx_transfer_read(connection, buf+reader->count, sizeof(reader->pending)-1-reader->count);
        if (got <= 0) return -1;
        reader->count += got;
        buf[reader->count] = 0;
        if ((end = strstr(buf, "\r\n\r\n"))) break;
    }
    reader->offset = end+4-buf;
    char saved = buf[reader->offset];
    buf[reader->offset] = 0;
    if (strncmp(buf, "HTTP/1.1 200 ", 13) && strncmp(buf, "HTTP/1.0 200 ", 13)) return -1;
    long length = -1;
    for (char *line = strstr(buf, "\r\n"); line && line[2]; line = strstr(line+2, "\r\n")) {
        line += 2;
        if (!strncasecmp(line, "Content-Length:", 15)) {
            char *p = line+15, *tail;
            while (*p == ' ' || *p == '\t') ++p;
            if (!isdigit((unsigned char)*p) || length >= 0) return -1;
            errno = 0;
            unsigned long parsed = strtoul(p, &tail, 10);
            while (*tail == ' ' || *tail == '\t') ++tail;
            if (errno || parsed > 0x7fffffffUL || strncmp(tail, "\r\n", 2)) return -1;
            length = parsed;
        }
        if (!strncasecmp(line, "Transfer-Encoding:", 18)) return -1;
    }
    if (length < 0) return -1;
    char *name = strstr(buf, "filename=\"");
    if (filename && name) {
        name += 10;
        unsigned n = 0;
        while (name[n] && name[n] != '"') {
            unsigned char c = name[n];
            if (n >= 254 || c < 32 || c == 127 || c == '/' || c == '\\' || c == ':') return -1;
            filename[n] = c; ++n;
        }
        if (name[n] != '"' || !n) return -1;
        filename[n] = 0;
        if (!strcmp(filename, ".") || !strcmp(filename, "..")) return -1;
    }
    buf[reader->offset] = saved;
    return length;
}

int http_read(struct http_reader *reader, u8 *buf, u32 len)
{
    if (wx_transfer_expired(reader->deadline)) return -ETIMEDOUT;
    u32 available = reader->count-reader->offset;
    if (available) {
        u32 n = available < len ? available : len;
        memcpy(buf, reader->pending+reader->offset, n);
        reader->offset += n;
        return n;
    }
    return wx_transfer_read(reader->connection, buf, len);
}

int network_read(int connection, u8 *buf, u32 len)
{
	u32 read = 0;
	s32 ret = -1;

	while (read < len)
	{
		ret = wx_transfer_read(connection, buf + read, len - read);
		if (ret < 0)
			return ret;

		if (!ret)
			break;

		read += ret;
	}

	return read;
}
