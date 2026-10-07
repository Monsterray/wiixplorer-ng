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
#include <malloc.h>
#include <climits>
#include <new>
#include <ogc/irq.h>
#include <ogc/cache.h>
#include "Diagnostics/MemoryProbes.h"
#include "Tools/tools.h"
#include "BufferCircle.hpp"

BufferCircle::BufferCircle()
{
	which = 0;
	BufferBlockSize = 0;
}

BufferCircle::~BufferCircle()
{
	FreeBuffer();
	SoundBuffer.clear();
	BufferSize.clear();
	BufferReady.clear();
}

bool BufferCircle::SetBufferBlockSize(int size)
{
    if(size<0 || size>INT_MAX-32) return false;
    std::vector<u8*> staged;
    try { staged.resize(Size(),NULL); } catch(const std::bad_alloc &) { return false; }
    for(int i=0;i<Size();++i) {
        if(size) { staged[i]=(u8*)memalign(32,ALIGN32(size)); WX_MEMORY_ALLOC(CPU,WX_MEM_AUDIO_RING,staged[i],ALIGN32(size)); }
        if(size && !staged[i]) { for(size_t j=0;j<staged.size();++j) { WX_MEMORY_FREE(CPU,WX_MEM_AUDIO_RING,staged[j],ALIGN32(size)); free(staged[j]); } return false; }
    }
    FreeBuffer(); SoundBuffer.swap(staged); BufferBlockSize=size;
    return true;
}

bool BufferCircle::Resize(int size)
{
    if(size<0 || size>UINT16_MAX) return false; // which is a u16 API index.
    if(size==Size()) return true;
    if(size<Size()) { while(size<Size()) RemoveBuffer(Size()-1); return true; }
    std::vector<u8*> buffers;
    std::vector<u32> sizes;
    std::vector<bool> ready;
    const int old=Size();
    try { buffers=SoundBuffer; sizes=BufferSize; ready=BufferReady;
          buffers.resize(size,NULL); sizes.resize(size,0); ready.resize(size,false); }
    catch(const std::bad_alloc &) { return false; }
    for(int i=old;i<size;++i) {
        if(BufferBlockSize) { buffers[i]=(u8*)memalign(32,ALIGN32(BufferBlockSize)); WX_MEMORY_ALLOC(CPU,WX_MEM_AUDIO_RING,buffers[i],ALIGN32(BufferBlockSize)); }
        if(BufferBlockSize && !buffers[i]) { for(int j=old;j<i;++j) { WX_MEMORY_FREE(CPU,WX_MEM_AUDIO_RING,buffers[j],ALIGN32(BufferBlockSize)); free(buffers[j]); } return false; }
    }
    SoundBuffer.swap(buffers); BufferSize.swap(sizes); BufferReady.swap(ready);
    return true;
}

void BufferCircle::RemoveBuffer(int pos)
{
	if(!Valid(pos))
		return;

	if(SoundBuffer[pos] != NULL) {
		WX_MEMORY_FREE(CPU,WX_MEM_AUDIO_RING,SoundBuffer[pos],ALIGN32(BufferBlockSize));
		free(SoundBuffer[pos]);
	}

	SoundBuffer.erase(SoundBuffer.begin()+pos);
	BufferSize.erase(BufferSize.begin()+pos);
	BufferReady.erase(BufferReady.begin()+pos);
	if(pos<(int)which) --which;
	if(which>=Size()) which=0;
}

void BufferCircle::ClearBuffer()
{
	for(int i = 0; i < Size(); i++)
	{
		BufferSize[i] = 0;
		BufferReady[i] = false;
	}
	which = 0;
}

void BufferCircle::FreeBuffer()
{
	for(int i = 0; i < Size(); i++)
	{
		if(SoundBuffer[i] != NULL) {
			WX_MEMORY_FREE(CPU,WX_MEM_AUDIO_RING,SoundBuffer[i],ALIGN32(BufferBlockSize));
			free(SoundBuffer[i]);
		}

		SoundBuffer[i] = NULL;
		BufferSize[i] = 0;
		BufferReady[i] = false;
	}
}

void BufferCircle::LoadNext()
{
	if(!Size()) { which=0; return; }
	unsigned irq=IRQ_Disable();
	BufferReady[which] = false;
	BufferSize[which] = 0;
	which = Next();
	IRQ_Restore(irq);
}

void BufferCircle::SetBufferReady(int pos, bool state)
{
	if(!Valid(pos))
		return;

	if(state && SoundBuffer[pos] && BufferSize[pos]) DCFlushRange(SoundBuffer[pos],BufferSize[pos]);
	unsigned irq=IRQ_Disable();
	BufferReady[pos] = state && SoundBuffer[pos] && BufferSize[pos]>0;
	IRQ_Restore(irq);
}

void BufferCircle::SetBufferSize(int pos, int size)
{
	if(!Valid(pos))
		return;

	unsigned irq=IRQ_Disable();
	if(size<0 || (u32)size>BufferBlockSize) { BufferSize[pos]=0; BufferReady[pos]=false; }
	else BufferSize[pos] = size;
	IRQ_Restore(irq);
}
