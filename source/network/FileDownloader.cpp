/***************************************************************************
 * Copyright (C) 2010
 * by Dimok
 *
 * This software is provided 'as-is', without any express or implied
 * warranty. In no event will the authors be held liable for any
 * damages arising from the use of this software.
 *
 * Permission is granted to anyone to use this software for any
 * purpose, including commercial applications, and to alter it and
 * redistribute it freely, subject to the following restrictions:
 *
 * 1. The origin of this software must not be misrepresented; you
 * must not claim that you wrote the original software. If you use
 * this software in a product, an acknowledgment in the product
 * documentation would be appreciated but is not required.
 *
 * 2. Altered source versions must be plainly marked as such, and
 * must not be misrepresented as being the original software.
 *
 * 3. This notice may not be removed or altered from any source
 * distribution.
 *
 * for WiiXplorer 2010
 ***************************************************************************/
#include <ogcsys.h>
#include <stdio.h>
#include <string.h>
#include "http.h"
#include "FileOperations/TransferFile.h"
#include "FileOperations/fileops.h"
#include "Prompts/PromptWindows.h"
#include "Prompts/ProgressWindow.h"

/****************************************************************************
 * Download a file from a given url with a Progressbar
 ****************************************************************************/
int DownloadFileToMem(const char *url, u8 **inbuffer, u32 *size)
{
    if (inbuffer) *inbuffer = NULL;
    if (size) *size = 0;
	if(!url || !inbuffer || !size || strlen(url) > 2048 || strpbrk(url, "\r\n") || strncasecmp(url, "http://", strlen("http://")) != 0)
	{
		ThrowMsg(tr("Error:"), tr("Not a valid URL"));
		return -1;
	}
	char *path = strchr(url + strlen("http://"), '/');

	if(!path)
	{
		ThrowMsg(tr("Error:"), tr("Not a valid URL path"));
		return -2;
	}

	int domainlength = path - url - strlen("http://");

	if(domainlength <= 0 || domainlength > 253)
	{
		ThrowMsg(tr("Error:"), tr("Not a valid domain"));
		return -3;
	}

	char domain[domainlength + 1];
	strncpy(domain, url + strlen("http://"), domainlength);
	domain[domainlength] = '\0';

	int connection = GetConnection(domain);

	if(connection < 0)
	{
		ThrowMsg(tr("Error:"), tr("Could not connect to the server."));
		return -4;
	}

	char header[1024];
	int headerSize = snprintf(header, sizeof(header),
		"GET %s HTTP/1.1\r\nHost: %s\r\nReferer: %s\r\n"
		"User-Agent: WiiXplorer\r\nPragma: no-cache\r\n"
		"Cache-Control: no-cache\r\nConnection: close\r\n\r\n",
		path, domain, domain);
	if(headerSize < 0 || headerSize >= (int)sizeof(header))
	{
		net_close(connection);
		return -2;
	}

	char filename[255];
	memset(filename, 0, sizeof(filename));

	http_reader reader;
	int filesize = network_request(&reader, connection, header, filename);

	if(filesize <= 0 || filesize > 16*1024*1024)
	{
		net_close(connection);
		ThrowMsg(tr("Error:"), tr("Filesize is 0 Byte."));
		return -5;
	}

	u32 blocksize = 16*1024;

	*inbuffer = NULL; *size = 0;
	u8 * buffer = (u8 *) malloc(filesize);
	if(!buffer)
	{
		net_close(connection);
		ThrowMsg(tr("Error:"), tr("Not enough memory."));
		return -6;
	}

	u32 done = 0;

	while(done < filesize)
	{
		if(ProgressWindow::Instance()->IsCanceled())
		{
			free(buffer);
			StopProgress();
			net_close(connection);
			return PROGRESS_CANCELED;
		}

		ShowProgress(done, filesize, filename);

		if(blocksize > filesize - done)
			blocksize = filesize - done;


		s32 read = http_read(&reader, buffer+done, blocksize);

		if(read < 0)
		{
			free(buffer);
			StopProgress();
			net_close(connection);
			ThrowMsg(tr("Error:"), tr("Transfer failed"));
			return -8;
		}
		else if(!read)
			break;

		done += read;
	}
	// finish up the progress
	FinishProgress(filesize);

	StopProgress();
	net_close(connection);

	if (done != (u32)filesize) { free(buffer); return -8; }
	*inbuffer = buffer;
	*size = filesize;

	return 1;
}

/****************************************************************************
 * Download a file from a given url to a given path with a Progressbar
 ****************************************************************************/
int DownloadFileToPath(const char *orig_url, const char *dest, bool UseFilename)
{
	if(!orig_url || !dest || strlen(orig_url) > 2048 || strpbrk(orig_url, "\r\n"))
	{
		ThrowMsg(tr("Error:"), tr("No URL or Path specified."));
		return -2;
	}

	bool addhttp = false;

	if(strncasecmp(orig_url, "http://", strlen("http://")) != 0)
	{
		addhttp = true;
	}

	char url[strlen(orig_url) + (addhttp ? strlen("http://") : 0) + 1];

	if(addhttp)
		snprintf(url, sizeof(url), "http://%s", orig_url);
	else
		strcpy(url, orig_url);

	char *path = strchr(url + strlen("http://"), '/');

	if(!path)
	{
		ThrowMsg(tr("Error:"), tr("Not a valid URL path"));
		return -2;
	}

	int domainlength = path - url - strlen("http://");

	if(domainlength <= 0 || domainlength > 253)
	{
		ThrowMsg(tr("Error:"), tr("Not a valid domain"));
		return -3;
	}

	char domain[domainlength + 1];
	strncpy(domain, url + strlen("http://"), domainlength);
	domain[domainlength] = '\0';

	int connection = GetConnection(domain);

	if(connection < 0)
	{
		ThrowMsg(tr("Error:"), tr("Could not connect to the server."));
		return -4;
	}

	char header[1024];
	int headerSize = snprintf(header, sizeof(header),
		"GET %s HTTP/1.1\r\nHost: %s\r\nReferer: %s\r\n"
		"User-Agent: WiiXplorer\r\nPragma: no-cache\r\n"
		"Cache-Control: no-cache\r\nConnection: close\r\n\r\n",
		path, domain, domain);
	if(headerSize < 0 || headerSize >= (int)sizeof(header))
	{
		net_close(connection);
		return -2;
	}

	char filename[255];
	memset(filename, 0, sizeof(filename));

	http_reader reader;
	int filesize = network_request(&reader, connection, header, filename);

	if(filesize <= 0)
	{
		net_close(connection);
		ShowError(tr("Filesize is 0 Byte."));
		return -5;
	}

	u32 blocksize = 16*1024;

	u8 *buffer = (u8 *) malloc(blocksize);
	if(!buffer)
	{
		net_close(connection);
		ThrowMsg(tr("Error:"), tr("Not enough memory."));
		return -6;
	}

	std::string destPath = dest;

	if(UseFilename)
	{
		if(destPath.empty() || destPath[destPath.size()-1] != '/')
			destPath += '/';

		CreateSubfolder(destPath.c_str());

		destPath += filename;
	}

	wx_transfer_file transfer;
	FILE *file = wx_transfer_begin(&transfer, destPath.c_str()) == 0
		? fopen(transfer.staged, "wb") : NULL;
	if(!file)
	{
		wx_transfer_abort(&transfer);
		net_close(connection);
		free(buffer);
		ThrowMsg(tr("Error:"), tr("Cannot write to destination."));
		return -7;
	}

	u32 done = 0;

	StartProgress(tr("Downloading file..."));

	while(done < filesize)
	{
		if(ProgressWindow::Instance()->IsCanceled())
		{
			free(buffer);
			StopProgress();
			net_close(connection);
			fclose(file);
			wx_transfer_abort(&transfer);
			return PROGRESS_CANCELED;
		}

		ShowProgress(done, filesize, filename);

		if(blocksize > filesize - done)
			blocksize = filesize - done;

		s32 read = http_read(&reader, buffer, blocksize);

		if(read < 0)
		{
			free(buffer);
			StopProgress();
			net_close(connection);
			fclose(file);
			wx_transfer_abort(&transfer);
			ThrowMsg(tr("Error:"), tr("Failed reading from network"));
			return -8;
		}
		else if(!read)
			break;

		if (fwrite(buffer, 1, read, file) != (size_t)read) break;

		done += read;
	}

	// finish up the progress
	FinishProgress(filesize);

	free(buffer);
	StopProgress();
	net_close(connection);
	int closeResult = fclose(file);
	if (done != (u32)filesize || closeResult != 0 ||
		wx_transfer_publish(&transfer, transfer.staged, destPath.c_str()) != 0) {
		wx_transfer_abort(&transfer); return -8;
	}
	return done;
}
