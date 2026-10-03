/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "TransferBench.h"
#if WX_DEBUG_BUILD
#include "FileOperations/fileops.h"
#include "DeviceControls/DeviceHandler.hpp"
#include <malloc.h>
#include <unistd.h>
#include <errno.h>
#include <sys/statvfs.h>
#include "network/TransferSocket.h"
#include <ogc/lwp_watchdog.h>
#include <stdio.h>
#include <string.h>
#include <zlib.h>
#include <sys/stat.h>

static int BenchDevice(const char *directory)
{
    if (!directory || strlen(directory)>700 || strstr(directory,"..")) return -1;
    if (!strncmp(directory,"sd:/",4)) return SD;
    if (!strncmp(directory,"usb",3) && directory[3]>='1' && directory[3]<='8' &&
        directory[4]==':' && directory[5]=='/') return USB1+directory[3]-'1';
    return -1;
}

static bool CheckCopy(const char *path, u32 expected)
{
    FILE *f = fopen(path, "rb");
    if (!f) return false;
    unsigned char buffer[16384];
    size_t n,total=0;
    u32 crc = crc32(0, NULL, 0);
    while ((n=fread(buffer, 1, sizeof(buffer), f))) {
        total+=n;
        if (total>8388608) break;
        crc = crc32(crc, buffer, n);
    }
    bool okay = !ferror(f) && total==8388608 && crc == expected;
    if (fclose(f) != 0) okay = false;
    return okay;
}

void RunCopyBenchmark(const char *directory)
{
    // Explicit debug argument only; refuse to reuse an existing directory.
    if (BenchDevice(directory)<0 || mkdir(directory,0700) != 0) return;
    char source[768], destination[768], report[768];
    snprintf(source,sizeof(source),"%s/source",directory);
    snprintf(destination,sizeof(destination),"%s/destination",directory);
    snprintf(report,sizeof(report),"%s/copy-benchmark.csv",directory);
    FILE *f=fopen(source,"wb");
    u32 crc=crc32(0,NULL,0), seed=42;
    bool okay=f!=NULL;
    unsigned char buffer[16384];
    for (unsigned chunk=0;okay && chunk<512;++chunk) {
        for (unsigned i=0;i<sizeof(buffer);++i) {
            seed ^= seed<<13; seed ^= seed>>17; seed ^= seed<<5; buffer[i]=seed;
        }
        crc=crc32(crc,buffer,sizeof(buffer));
        okay=fwrite(buffer,1,sizeof(buffer),f)==sizeof(buffer) && !wx_transfer_cancelled();
    }
    if (f && fclose(f)!=0) okay=false;
    f=okay ? fopen(report,"wb") : NULL;
    if (f) {
        fprintf(f,"buffer_bytes,repeat,bytes,microseconds,verified\n");
        const u32 sizes[]={32768,65536,71680,131072,262144};
        for (unsigned i=0;okay && i<5;++i) for(unsigned repeat=0;okay && repeat<3;++repeat) {
            u64 start=gettime();
            int result=CopyFile(source,destination,sizes[i]);
            u64 elapsed=ticks_to_microsecs(gettime()-start);
            okay=result>0 && CheckCopy(destination,crc);
            fprintf(f,"%u,%u,8388608,%llu,%u\n",sizes[i],repeat,elapsed,okay);
            remove(destination);
        }
        fclose(f);
    }
    remove(source);
    remove(destination);
    // Retain the report and its private directory for the leased test runner.
}

void RunStorageBenchmark(const char *directory, const char *reportDirectory)
{
    const int dev=BenchDevice(directory);
    if (dev<0) return;
    if (!reportDirectory) reportDirectory=directory;
    if (BenchDevice(reportDirectory)<0) return;
    DeviceHandler *devices=DeviceHandler::Instance();
    if (!devices->IsInserted(dev)) return;
    char root[8];
    snprintf(root,sizeof(root),"%s:/",DeviceName[dev]);
    struct statvfs space;
    // Two 8 MiB fixtures plus metadata; leave at least 16 MiB free.
    if (statvfs(root,&space)!=0 || !space.f_frsize ||
        (u64)space.f_bavail*space.f_frsize < 32ULL*1024*1024) return;
    if (mkdir(directory,0700)!=0) return; // Never overwrite someone else's files.
    const bool separate=strcmp(directory,reportDirectory)!=0;
    if (separate && mkdir(reportDirectory,0700)!=0) { rmdir(directory); return; }
    const size_t block=262144, bytes=8388608;
    unsigned char *buffer=(unsigned char *)memalign(32,block);
    char source[768],destination[768],report[768],metadata[768];
    snprintf(source,sizeof(source),"%s/source",directory);
    snprintf(destination,sizeof(destination),"%s/destination",directory);
    snprintf(report,sizeof(report),"%s/storage-benchmark.csv",reportDirectory);
    snprintf(metadata,sizeof(metadata),"%s/storage-metadata.csv",reportDirectory);
    PartitionHandle *handle=dev==SD ? devices->GetSDHandle() : devices->GetUSBFromDev(dev);
    int part=dev==SD ? 0 : devices->PartToPortPart(dev-USB1);
    PartitionFS *record=handle ? handle->GetPartitionRecord(part) : NULL;
    FILE *f=buffer ? fopen(metadata,"wb") : NULL;
    if (f && record) {
        // The mounted FAT driver's statvfs reports allocation-unit bytes.
        unsigned cluster=!strncmp(record->FSName,"FAT",3) ? space.f_frsize : 0;
        fprintf(f,"device,filesystem,start_lba,sectors,sector_bytes,cluster_bytes,partition_type,free_bytes\n");
        fprintf(f,"%s,%s,%llu,%llu,%u,%u,%u,%llu\n",DeviceName[dev],record->FSName,
                record->LBA_Start,record->SecCount,handle->GetSectorSize(),cluster,
                record->PartitionType,(u64)space.f_bavail*space.f_frsize);
    }
    bool okay=f && record;
    if (f && fclose(f)!=0) okay=false;
    u32 seed=42,crc=crc32(0,NULL,0);
    if (okay) {
        for (size_t i=0;i<block;++i) {
            seed^=seed<<13; seed^=seed>>17; seed^=seed<<5; buffer[i]=seed;
        }
        // Payload generation and reference checksum stay outside timed I/O.
        for (size_t i=0;i<bytes/block;++i) crc=crc32(crc,buffer,block);
    }
    FILE *out=okay ? fopen(report,"wb") : NULL;
    if (out) {
        fprintf(out,"operation,buffer_bytes,repeat,bytes,microseconds,verified\n");
        for (unsigned repeat=0;okay && repeat<3;++repeat) {
            u64 start=gettime();
            f=fopen(source,"wb");
            okay=f!=NULL;
            for (size_t i=0;okay && i<bytes/block;++i)
                okay=fwrite(buffer,1,block,f)==block && !wx_transfer_cancelled();
            if (f && fclose(f)!=0) okay=false; // Include driver cache flush.
            u64 elapsed=ticks_to_microsecs(gettime()-start);
            okay=okay && CheckCopy(source,crc);
            fprintf(out,"write,%u,%u,%u,%llu,%u\n",(unsigned)block,repeat,(unsigned)bytes,elapsed,okay);
            if (!okay) break;
            start=gettime();
            f=fopen(source,"rb");
            okay=f!=NULL;
            size_t total=0,n=0;
            while (okay && (n=fread(buffer,1,block,f))) {
                total+=n;
                okay=total<=bytes && !wx_transfer_cancelled();
            }
            if (f && ferror(f)) okay=false;
            if (f && fclose(f)!=0) okay=false;
            elapsed=ticks_to_microsecs(gettime()-start);
            okay=okay && total==bytes && CheckCopy(source,crc);
            fprintf(out,"read,%u,%u,%u,%llu,%u\n",(unsigned)block,repeat,(unsigned)bytes,elapsed,okay);
        }
        const u32 sizes[]={131072,262144};
        // Interleave and reverse each round to reduce write-cache/order bias.
        for (unsigned repeat=0;okay && repeat<3;++repeat) for (unsigned order=0;okay && order<2;++order) {
            unsigned i=(repeat&1) ? order : 1-order;
            u64 start=gettime();
            int result=CopyFile(source,destination,sizes[i]);
            u64 elapsed=ticks_to_microsecs(gettime()-start);
            okay=result>0 && CheckCopy(destination,crc);
            fprintf(out,"copy,%u,%u,%u,%llu,%u\n",sizes[i],repeat,(unsigned)bytes,elapsed,okay);
            if (remove(destination)!=0) okay=false;
        }
        if (fclose(out)!=0) okay=false;
    }
    if (remove(source)!=0 && errno!=ENOENT) okay=false;
    if (remove(destination)!=0 && errno!=ENOENT) okay=false;
    free(buffer);
    if (separate && rmdir(directory)!=0) okay=false;
    snprintf(report,sizeof(report),"%s/storage-complete",reportDirectory);
    f=fopen(report,"wb");
    if (f) { fprintf(f,"%u",okay && out); fclose(f); }
    // Publish completion only after fixtures have been removed.
}
#endif
