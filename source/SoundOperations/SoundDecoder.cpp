/****************************************************************************
 * Copyright (C) 2009-2013 Dimok
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 ****************************************************************************/
#include <gccore.h>
#include <malloc.h>
#include <string.h>
#include <unistd.h>
#include "Diagnostics/MemoryProbes.h"
#include "SoundDecoder.hpp"

static const u32 FixedPointShift = 15;
static const u32 FixedPointScale = 1 << FixedPointShift;

SoundDecoder::SoundDecoder()
{
	file_fd = NULL;
	Init();
}

SoundDecoder::SoundDecoder(const char * filepath)
{
	file_fd = new CFile(filepath, "rb");
	Init();
}

SoundDecoder::SoundDecoder(const u8 * buffer, int size)
{
	file_fd = new CFile(buffer, size);
	Init();
}

SoundDecoder::~SoundDecoder()
{
	ExitRequested = true;
	while(Decoding)
		usleep(1000);

	if(file_fd)
		delete file_fd;
	file_fd = NULL;

	WX_MEMORY_FREE(CPU,WX_MEM_AUDIO_RESAMPLE,ResampleBuffer,SoundBuffer.Capacity());
	free(ResampleBuffer);
}

void SoundDecoder::Init()
{
	SoundType = SOUND_RAW;
	SoundBlocks = Settings.SoundblockCount;
	SoundBlockSize = Settings.SoundblockSize;
	ResampleTo48kHz = Settings.ResampleTo48kHz;
	CurPos = 0;
	whichLoad = 0;
	Loop = false;
	EndOfFile = false;
	Decoding = false;
	ExitRequested = false;
    // Match the existing settings UI's 512 KiB ring allowance. Invalid file
    // settings fail closed instead of wrapping a signed count or multiplying.
    int blocks=Settings.SoundblockCount;
    if(blocks<3 || SoundBlockSize<4096 || SoundBlockSize>65535 ||
       blocks>512*1024/SoundBlockSize || !SoundBuffer.SetBufferBlockSize(SoundBlockSize) || !SoundBuffer.Resize(blocks)) {
        ExitRequested=true;EndOfFile=true;
    }
	ResampleBuffer = NULL;
	ResampleRatio = 0;
}

int SoundDecoder::Rewind()
{
	CurPos = 0;
	EndOfFile = false;
	file_fd->rewind();

	return 0;
}

int SoundDecoder::Read(u8 * buffer, int buffer_size, int pos UNUSED)
{
	int ret = file_fd->read(buffer, buffer_size);
	CurPos += ret;

	return ret;
}

void SoundDecoder::EnableUpsample(void)
{
	if(   (ResampleBuffer == NULL)
	   && IsStereo() && Is16Bit()
	   && SampleRate != 32000
	   && SampleRate != 48000)
	{
        if(SampleRate<=0 || SampleRate>48000) { ExitRequested=true;return; }
        u32 ratio=(u64)FixedPointScale*SampleRate/48000;
        int block=((u64)SoundBlockSize*ratio/FixedPointScale)&~3;
        if(!ratio || block<4) { ExitRequested=true;return; }
        ResampleBuffer=(u8*)memalign(32,SoundBuffer.Capacity());
        WX_MEMORY_ALLOC(CPU,WX_MEM_AUDIO_RESAMPLE,ResampleBuffer,SoundBuffer.Capacity());
        if(!ResampleBuffer) { ExitRequested=true;return; }
        ResampleRatio=ratio;SoundBlockSize=block;SampleRate=48000;
	}
}

void SoundDecoder::Upsample(s16 *src, s16 *dst, u32 nr_src_samples, u32 nr_dst_samples)
{
	int timer = 0;

	for(u32 i = 0, n = 0; i < nr_dst_samples; i += 2)
	{
		if((n+3) < nr_src_samples) {
			// simple fixed point linear interpolation
			dst[i]   = src[n] +   ( ((src[n+2] - src[n]  ) * timer) >> FixedPointShift );
			dst[i+1] = src[n+1] + ( ((src[n+3] - src[n+1]) * timer) >> FixedPointShift );
		}
		else {
			dst[i]   = src[n];
			dst[i+1] = src[n+1];
		}

		timer += ResampleRatio;

		if(timer >= (int)FixedPointScale) {
			n += 2;
			timer -= FixedPointScale;
		}
	}
}

void SoundDecoder::Decode()
{
	if(!file_fd || ExitRequested || EndOfFile)
		return;

	// check if we are not at the pre-last buffer (last buffer is playing)
	u16 whichPlaying = SoundBuffer.Which();
	if(	   (whichLoad == (whichPlaying-2))
		|| ((whichPlaying == 0) && (whichLoad == SoundBuffer.Size()-2))
		|| ((whichPlaying == 1) && (whichLoad == SoundBuffer.Size()-1)))
	{
		return;
	}

	Decoding = true;

	int done  = 0;
    bool rewoundWithoutProgress=false;
	u8 * write_buf = SoundBuffer.GetBuffer(whichLoad);
	if(!write_buf)
	{
		ExitRequested = true;
		Decoding = false;
		return;
	}

	if(ResampleTo48kHz && !ResampleBuffer)
		EnableUpsample();
    if(ExitRequested) { Decoding=false;return; }

	while(done < SoundBlockSize)
	{
		int ret = Read(&write_buf[done], SoundBlockSize-done, Tell());

		if(ret <= 0)
		{
			if(Loop && ret==0 && !rewoundWithoutProgress)
			{
                rewoundWithoutProgress=true;
				Rewind();
				continue;
			}
			else
			{
				EndOfFile = true;
				break;
			}
		}

        if(ret>SoundBlockSize-done) { ExitRequested=true;Decoding=false;return; }
        rewoundWithoutProgress=false;
		done += ret;
	}

	if(done > 0)
	{
		// check if we need to resample
		if(ResampleBuffer && ResampleRatio)
		{
			done &= ~3;
			memcpy(ResampleBuffer, write_buf, done);

			int src_samples = done >> 1;
			int dest_samples=(u64)src_samples*FixedPointScale/ResampleRatio;
			if(!src_samples || (u32)dest_samples>SoundBuffer.Capacity()/2) { ExitRequested=true;Decoding=false;return; }
			dest_samples &= ~0x01;
			Upsample((s16*)ResampleBuffer, (s16*)write_buf, src_samples, dest_samples);
			done = dest_samples << 1;
		}

		SoundBuffer.SetBufferSize(whichLoad, done);
		SoundBuffer.SetBufferReady(whichLoad, true);
		if(++whichLoad >= SoundBuffer.Size())
			whichLoad = 0;
	}

	// check if next in queue needs to be filled as well and do so
	if(!SoundBuffer.IsBufferReady(whichLoad))
		Decode();

	Decoding = false;
}

