/****************************************************************************
 * Copyright (C) 2009 - 2013 Dimok
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
#include <asndlib.h>
#include <unistd.h>
#include <climits>
#include <new>
#include "Diagnostics/MemoryProbes.h"
#include "Memory/MemoryBudget.h"
#include "Controls/Application.h"
#include "WiiMovie.hpp"
#include "ImageOperations/TextureConverter.h"
#include "SoundOperations/MusicPlayer.h"
#include "VideoOperations/video.h"

static BufferCircle * soundbuffer = NULL;

WiiMovie::WiiMovie(const char * filepath)
{
	currentFrame = 0.0f;
	fps = 0.0f;
	whichLoad = 0;
	ExitRequested = false;
	Playing = false;
	volume = 255*Settings.MusicVolume/100;
	ReadThread = LWP_THREAD_NULL;
	DecThread = LWP_THREAD_NULL;
	ReadStackBuf = DecStackBuf = NULL;
	FrameBufCount = 0;
	FrameBytes = 0; workersReady=false; decodeFailed=false;

	for(int i = 0; i < FRAME_BUFFERS; ++i)
		FrameBuf[i] = NULL;

	background = new GuiImage(screenwidth, screenheight, (GXColor){0, 0, 0, 255});

	trigB = new GuiTrigger();
	trigB->SetButtonOnlyTrigger(-1, WiiControls.BackButton | ClassicControls.BackButton << 16, GCControls.BackButton);

	exitBtn = new GuiButton(1, 1);
	exitBtn->SetTrigger(trigB);
	exitBtn->Clicked.connect(this, &WiiMovie::OnExitClick);

	MusicPlayer::Instance()->Pause();

	string file(filepath);
	Video = openVideo(file);
	if(!Video)
	{
		ShowError(tr("Unsupported format!"));
		ExitRequested = true;
		Application::Instance()->PushForDelete(this);
		return;
	}

	SndChannels = Video->getNumChannels();
	SndFrequence = Video->getFrequency();
	fps = Video->getFps();
	const u32 samples=Video->getMaxAudioSamples();
    if(Video->hasSound() && (SndChannels<1 || SndChannels>2 || !samples ||
       samples>(u32)(INT_MAX/(SndChannels*2*FRAME_BUFFERS)))) {
        ExitRequested=true; Application::Instance()->PushForDelete(this); return;
    }
    maxSoundSize=Video->hasSound() ? samples*SndChannels*2 : 0;

	if(Video->hasSound())
	{
		soundbuffer = &SoundBuffer;
        if((uint64_t)maxSoundSize*FRAME_BUFFERS*SND_BUFFERS>WxMemoryBudget() ||
           !SoundBuffer.Resize(SND_BUFFERS) || !SoundBuffer.SetBufferBlockSize(maxSoundSize*FRAME_BUFFERS)) {
            soundbuffer=NULL; ExitRequested=true; Application::Instance()->PushForDelete(this); return;
        }
	}

	const int ReadStackBufSize = 32768;
	const int DecStackBufSize = 16384;

	ReadStackBuf = (u8 *) memalign(32, ReadStackBufSize + DecStackBufSize);
	WX_MEMORY_ALLOC(THREADS,WX_MEM_MOVIE_STACK,ReadStackBuf,ReadStackBufSize+DecStackBufSize);
	if(!ReadStackBuf)
	{
		ShowError(tr("Not enough memory"));
		ExitRequested = true;
		Application::Instance()->PushForDelete(this);
		return;
	}

	DecStackBuf = ReadStackBuf + ReadStackBufSize;

#if WX_PROBE_THREADS && WX_PROBE_LEVEL>=2
    memset(ReadStackBuf,0xa5,ReadStackBufSize+DecStackBufSize);
#endif
    int rc=LWP_CreateThread(&ReadThread,UpdateThread,this,ReadStackBuf,ReadStackBufSize,75);
    if(rc>=0) rc=LWP_CreateThread(&DecThread,DecodeThread,this,DecStackBuf,DecStackBufSize,70);
    if(rc<0) { ExitRequested=true; Application::Instance()->PushForDelete(this); }
    workersReady=true;
}

WiiMovie::~WiiMovie()
{
	Playing = false;
	ExitRequested = true;


	if(ReadThread != LWP_THREAD_NULL)
	{
		LWP_ResumeThread(ReadThread);
		LWP_JoinThread(ReadThread, NULL);
	}
	if(DecThread != LWP_THREAD_NULL)
	{
		LWP_ResumeThread(DecThread);
		LWP_JoinThread(DecThread, NULL);
	}

    WX_MEMORY_FREE(CPU,WX_MEM_MOVIE_INPUT,EncodedFrame.data(),EncodedFrame.capacity());
    ASND_StopVoice(0); soundbuffer=NULL;
    MusicPlayer::Instance()->Resume();
    GX_DrawDone();
    for(int i=0;i<FRAME_BUFFERS;++i) {
        WX_MEMORY_FREE(GPU,WX_MEM_MOVIE_FRAME,FrameBuf[i],FrameBytes);
        MEM2_free(FrameBuf[i]);
    }

    WX_MEMORY_STACK(WX_MEM_MOVIE_STACK,ReadStackBuf,49152);
    WX_MEMORY_FREE(THREADS,WX_MEM_MOVIE_STACK,ReadStackBuf,49152);
    free(ReadStackBuf);

	delete background;
	delete exitBtn;
	delete trigB;

	if(Video)
	   closeVideo(Video);
}

bool WiiMovie::Play()
{
	if(!Video || ExitRequested || !workersReady)
		return false;

	Playing = true;
	PlayTime.reset();

	LWP_ResumeThread(ReadThread);
	LWP_ResumeThread(DecThread);

	return true;
}

void WiiMovie::Stop()
{
	ExitRequested = true;
}

void WiiMovie::SetVolume(int vol)
{
	volume = 255*vol/100;
	ASND_ChangeVolumeVoice(0, volume, volume);
}

void WiiMovie::OnExitClick(GuiButton *sender UNUSED, int pointer UNUSED, const POINT &p UNUSED)
{
	Application::Instance()->PushForDelete(this);
}

void WiiMovie::SetFullscreen()
{
	if(!Video)
		return;

	float newscale = 1.0f;

	if(width < screenwidth && height < screenheight)
	{
		if((screenheight - height) > (screenwidth - width))
		{
			newscale = (float) screenheight / (float) height;
		}
		else
		{
			newscale = (float) screenwidth / (float) width;
		}
	}
	else
	{
		if((height - screenheight) > (width - screenwidth))
		{
			newscale = (float) screenheight / (float) height;
		}
		else
		{
			newscale = (float) screenwidth / (float) width;
		}
	}

	SetScale(newscale);
}

void WiiMovie::SetFrameSize(int w, int h)
{
	if(!Video)
		return;

	SetScaleX((float) w /(float) GetWidth());
	SetScaleY((float) h /(float) GetHeight());
}

void WiiMovie::SetAspectRatio(float Aspect)
{
	if(!Video)
		return;

	float vidwidth = (float) GetHeight()*GetScaleY()*Aspect;

	SetScaleX((float) GetWidth()/vidwidth);
}

extern "C" void THPSoundCallback(int voice UNUSED)
{
	if(!soundbuffer || !soundbuffer->IsBufferReady())
		return;

	if(ASND_AddVoice(0, soundbuffer->GetBuffer(), soundbuffer->GetBufferSize()) != SND_OK)
	{
		return;
	}

	soundbuffer->LoadNext();
}

void * WiiMovie::UpdateThread(void *arg)
{
	WiiMovie * Movie = static_cast<WiiMovie *>(arg);

	while(!Movie->workersReady && !Movie->ExitRequested) usleep(100);
	while(!Movie->ExitRequested)
	{
		Movie->ReadNextFrame();

		usleep(5000);
	}
	return NULL;
}

void * WiiMovie::DecodeThread(void *arg)
{
	WiiMovie * Movie = static_cast<WiiMovie *>(arg);

	int oldFrame = 0;

	while(!Movie->workersReady && !Movie->ExitRequested) usleep(100);
	while(!Movie->ExitRequested)
	{
		if(!Movie->Playing)
			LWP_SuspendThread(Movie->DecThread);

		Movie->readDecodeMutex.lock();
        oldFrame=Movie->Video->getCurrentFrameNr();
        Movie->readDecodeMutex.unlock();
		if(Movie->ExitRequested) break;
		Movie->DecodeNextFrame();

        while(!Movie->ExitRequested) {
            Movie->readDecodeMutex.lock();
            bool same=oldFrame==Movie->Video->getCurrentFrameNr();
            Movie->readDecodeMutex.unlock();
            if(Movie->FrameBufCount<FRAME_BUFFERS && !same) break;
            usleep(100);
        }
	}

	return NULL;
}

void WiiMovie::ReadNextFrame()
{
	if(!Playing) LWP_SuspendThread(ReadThread);
	if(ExitRequested || !Playing) return;

	float FrameExpected = PlayTime.elapsed() * fps; // float is enough for up to 74 hours straight playing in 60 fps

	unsigned catchup=0;
	while(!ExitRequested && currentFrame < FrameExpected && catchup++<4)
	{
		readDecodeMutex.lock();
		Video->loadNextFrame();
		readDecodeMutex.unlock();
		if(!Video->valid()) { Playing=false;ExitRequested=true;decodeFailed=true;return; }

		currentFrame += 1.0f;

		if(Video->hasSound())
		{
			// check if we are not at the pre-last buffer (last buffer is playing)
			if(	(whichLoad == (SoundBuffer.Which()-2))
				|| ((SoundBuffer.Which() == 0) && (whichLoad == SoundBuffer.Size()-2))
				|| ((SoundBuffer.Which() == 1) && (whichLoad == SoundBuffer.Size()-1)))
			{
				return;
			}

            int currentSize=SoundBuffer.GetBufferSize(whichLoad);
            if(!SoundBuffer.GetBuffer(whichLoad) || currentSize<0 || (u32)currentSize>SoundBuffer.Capacity() ||
               (u32)maxSoundSize>SoundBuffer.Capacity()-(u32)currentSize) {
                Playing=false;ExitRequested=true;decodeFailed=true;return;
            }

			currentSize += Video->getCurrentBuffer((s16 *) (&SoundBuffer.GetBuffer(whichLoad)[currentSize]))*SndChannels*2;
			SoundBuffer.SetBufferSize(whichLoad, currentSize);

			if(currentSize >= (FRAME_BUFFERS-1) * maxSoundSize)
			{
				SoundBuffer.SetBufferReady(whichLoad, true);

				if(++whichLoad >= SoundBuffer.Size())
					whichLoad = 0;
			}

			if(SoundBuffer.IsBufferReady() && ASND_StatusVoice(0) == SND_UNUSED)
			{
				ASND_StopVoice(0);
				ASND_SetVoice(0, (SndChannels == 2) ? VOICE_STEREO_16BIT : VOICE_MONO_16BIT, SndFrequence, 0,
							  SoundBuffer.GetBuffer(), SoundBuffer.GetBufferSize(), volume, volume, THPSoundCallback);
				SoundBuffer.LoadNext();
			}
		}
	}
}

void WiiMovie::DecodeNextFrame()
{
    if(!Video || !Playing || ExitRequested || FrameBufCount>=FRAME_BUFFERS) return;
    readDecodeMutex.lock();
    bool copied=true;
#if WX_PROBE_LEVEL>0
    const uintptr_t oldAddress=(uintptr_t)EncodedFrame.data();const size_t oldCapacity=EncodedFrame.capacity();
#endif
    try { Video->copyCurrentFrame(EncodedFrame); } catch(const std::bad_alloc &) { copied=false; }
#if WX_PROBE_LEVEL>0
    if(EncodedFrame.capacity()!=oldCapacity) {
        WX_MEMORY_ALLOC(CPU,WX_MEM_MOVIE_INPUT,EncodedFrame.data(),EncodedFrame.capacity());
        WX_MEMORY_FREE(CPU,WX_MEM_MOVIE_INPUT,(const void*)oldAddress,oldCapacity);
    }
#endif
    readDecodeMutex.unlock();
    if(!copied) { Playing=false; ExitRequested=true; decodeFailed=true; return; }
    try { Video->decodeVideoFrame(VideoF,EncodedFrame); }
    catch(const std::bad_alloc &) { Playing=false; ExitRequested=true; decodeFailed=true; return; }
    if(!VideoF.getData()) return;
    const int w=VideoF.getWidth(),h=VideoF.getHeight();
    // GX texture dimensions, including padded 4x4 RGB565 tiles.
    if(w<=0 || h<=0 || w>1024 || h>1024) {
        Playing=false; ExitRequested=true; decodeFailed=true; return;
    }
    frameMutex.lock();
    if(width!=w || height!=h) {
        // Reserve room for the complete queue before accepting new dimensions.
        if((uint64_t)ALIGN(w)*ALIGN(h)*2*FRAME_BUFFERS>WxMemoryBudget()) {
            Playing=false; ExitRequested=true; decodeFailed=true; frameMutex.unlock(); return;
        }
        for(int i=0;i<FRAME_BUFFERS;++i) {
            WX_MEMORY_FREE(GPU,WX_MEM_MOVIE_FRAME,FrameBuf[i],FrameBytes);
            MEM2_free(FrameBuf[i]); FrameBuf[i]=NULL;
        }
        FrameBufCount=0; width=w; height=h; FrameBytes=ALIGN(w)*ALIGN(h)*2;
        SetFullscreen();
    }
    int slot=FrameBufCount;
    if(slot>=FRAME_BUFFERS) { frameMutex.unlock(); return; }
    if(!FrameBuf[slot]) {
        FrameBuf[slot]=(u8*)MEM2_alloc(FrameBytes);
        WX_MEMORY_ALLOC(GPU,WX_MEM_MOVIE_FRAME,FrameBuf[slot],FrameBytes);
    }
    if(!FrameBuf[slot]) {
        Playing=false; ExitRequested=true; decodeFailed=true; frameMutex.unlock(); return;
    }
    RGB8ToRGB565Stride(VideoF.getData(),FrameBuf[slot],width,height,VideoF.getPitch());
    ++FrameBufCount;
    frameMutex.unlock();
}

void WiiMovie::Draw()
{
	if(!Video)
		return;

	background->Draw();

	frameMutex.lock();
	if(FrameBufCount > 0)
	{
		if(FrameBuf[0])
			Menu_DrawImg(FrameBuf[0], width, height, GX_TF_RGB565, GetLeft(), GetTop(), 0.0f, 0.0f, scaleX, scaleY, alpha);

		GX_DrawDone(); // GPU has finished before this slot can be recycled.
		//! rotate FIFO
		if(FrameBufCount > 1)
		{
			u8 *tmp = FrameBuf[0];

			for(int i = 1; i < FrameBufCount; ++i)
				FrameBuf[i-1] = FrameBuf[i];

			//! set first on the last position to avoid unnecessary deallocate
			FrameBuf[FrameBufCount-1] = tmp;
			FrameBufCount--;
		}
	}
	frameMutex.unlock();
}

void WiiMovie::Update(GuiTrigger * t)
{
	if(decodeFailed.exchange(false)) { ShowError(tr("Not enough memory or invalid video dimensions")); Application::Instance()->PushForDelete(this); return; }
	exitBtn->Update(t);
}
