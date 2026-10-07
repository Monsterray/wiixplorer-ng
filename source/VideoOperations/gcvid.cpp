/***************************************************************************
 * Copyright (C) 2010
 * by thakis
 *
 * Modification and adjustment for the Wii by Dimok
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
 * gcvid.cpp
 ***************************************************************************/

#include "gcvid.h"

#include <cstdlib> //NULL
#include <cstring> //memcmp
#include <string>
#include <cassert>
#include <climits>
#include <cmath>
#include <new>
#include <sys/stat.h>
#include "Memory/MemoryBudget.h"
#include "Diagnostics/MemoryProbes.h"
using namespace std;

static u32 VideoBE32(const u8 *p) { return ((u32)p[0]<<24)|((u32)p[1]<<16)|((u32)p[2]<<8)|p[3]; }
static s16 VideoBE16(const u8 *p) { return (s16)(((u16)p[0]<<8)|p[1]); }
template<class T> static bool VideoWords(FILE *f,T &out,size_t bytes,size_t tag=0)
{
    u8 data[sizeof(T)];memset(&out,0,sizeof(out));
    if(bytes>sizeof(T) || fread(data,1,bytes,f)!=bytes || ferror(f)) return false;
    if(tag) memcpy(&out,data,tag);
    for(size_t i=tag;i<bytes;i+=4) { u32 word=VideoBE32(data+i);memcpy((u8*)&out+i,&word,4); }
    return true;
}
static bool readThpHeader(FILE *f,ThpHeader &h) { return VideoWords(f,h,sizeof(h),4); }
static bool readThpComponents(FILE *f,ThpComponents &c)
{
    u8 data[20];if(fread(data,1,20,f)!=20) return false;
    c.numComponents=VideoBE32(data);memcpy(c.componentTypes,data+4,16);return true;
}
static bool readThpVideoInfo(FILE *f,ThpVideoInfo &i,bool v11) { return VideoWords(f,i,v11?12:8); }
static bool readThpAudioInfo(FILE *f,ThpAudioInfo &i,bool v11) { bool okay=VideoWords(f,i,v11?16:12);if(!v11)i.numData=1;return okay; }
static bool readMthHeader(FILE *f,MthHeader &h) { return VideoWords(f,h,sizeof(h),4); }

struct DecStruct
{
  const u8* currSrcByte;
  u32 blockCount;
  u8 index;
  u8 shift;
};

void thpAudioInitialize(DecStruct& s, const u8* srcStart)
{
  s.currSrcByte = srcStart;
  s.blockCount = 2;
  s.index = (*s.currSrcByte >> 4) & 0x7;
  s.shift = *s.currSrcByte & 0xf;
  ++s.currSrcByte;
}

s32 thpAudioGetNewSample(DecStruct& s)
{
  //the following if is executed all 14 calls
  //to thpAudioGetNewSample() (once for each
  //microblock) because mask & 0xf can contain
  //16 different values and starts with 2
  if((s.blockCount & 0xf) == 0)
  {
	s.index = (*s.currSrcByte >> 4) & 0x7;
	s.shift = *s.currSrcByte & 0xf;
	++s.currSrcByte;
	s.blockCount += 2;
  }

  s32 ret;
  if((s.blockCount & 1) != 0)
  {
	s32 t = ((u32)*s.currSrcByte << 28) & 0xf0000000;
	ret = t >> 28; //this has to be an arithmetic shift
	++s.currSrcByte;
  }
  else
  {
	s32 t = ((u32)*s.currSrcByte << 24) & 0xf0000000;
	ret = t >> 28; //this has to be an arithmetic shift
  }

  ++s.blockCount;
  return ret;
}

int thpAudioDecode(s16 * destBuffer, const u8* srcBuffer, bool separateChannelsInOutput, bool isInputStereo)
{
  if(destBuffer == NULL || srcBuffer == NULL)
	return 0;

  u32 channelInSize=VideoBE32(srcBuffer),numSamples=VideoBE32(srcBuffer+4);

  const u8* srcChannel1 = srcBuffer + sizeof(ThpAudioBlockHeader);
  const u8* srcChannel2 = srcChannel1 + channelInSize;

  s16 table1[16],table2[16];
  for(unsigned i=0;i<16;++i) {table1[i]=VideoBE16(srcBuffer+8+i*2);table2[i]=VideoBE16(srcBuffer+40+i*2);}

  s16* destChannel1, * destChannel2;
  u32 delta;

  if(separateChannelsInOutput)
  {
	//separated channels in output
	destChannel1 = destBuffer;
	destChannel2 = destBuffer + numSamples;
	delta = 1;
  }
  else
  {
	//interleaved channels in output
	destChannel1 = destBuffer;
	destChannel2 = destBuffer + 1;
	delta = 2;
  }

  DecStruct s;
  if(!isInputStereo)
  {
	//mono channel in input

	thpAudioInitialize(s, srcChannel1);

	s16 prev1 = VideoBE16(srcBuffer+72);
	s16 prev2 = VideoBE16(srcBuffer+74);

	for(u32 i = 0; i < numSamples; ++i)
	{
	  s64 res = (s64)thpAudioGetNewSample(s);
	  res = (res * ((s64)1 << (s.shift+11))); //convert to 53.11 fixedpoint

	  //these values are 53.11 fixed point numbers
	  s64 val1 = table1[2*s.index];
	  s64 val2 = table1[2*s.index + 1];

	  //convert to 48.16 fixed point
	  res = (val1*prev1 + val2*prev2 + res) * 32;

	  //rounding:
	  u16 decimalPlaces = res & 0xffff;
	  if(decimalPlaces > 0x8000) //i.e. > 0.5
		//round up
		++res;
	  else if(decimalPlaces == 0x8000) //i.e. == 0.5
		if((res & 0x10000) != 0)
		  //round up every other number
		  ++res;

	  //get nonfractional parts of number, clamp to [-32768, 32767]
	  s32 final = (res >> 16);
	  if(final > 32767) final = 32767;
	  else if(final < -32768) final = -32768;

	  prev2 = prev1;
	  prev1 = final;
	  *destChannel1 = (s16)final;
	  *destChannel2 = (s16)final;
	  destChannel1 += delta;
	  destChannel2 += delta;
	}
  }
  else
  {
	//two channels in input - nearly the same as for one channel,
	//so no comments here (different lines are marked with XXX)

	thpAudioInitialize(s, srcChannel1);
	s16 prev1 = VideoBE16(srcBuffer+72);
	s16 prev2 = VideoBE16(srcBuffer+74);
	for(u32 i = 0; i < numSamples; ++i)
	{
	  s64 res = (s64)thpAudioGetNewSample(s);
	  res = (res * ((s64)1 << (s.shift+11)));
	  s64 val1 = table1[2*s.index];
	  s64 val2 = table1[2*s.index + 1];
	  res = (val1*prev1 + val2*prev2 + res) * 32;
	  u16 decimalPlaces = res & 0xffff;
	  if(decimalPlaces > 0x8000)
		++res;
	  else if(decimalPlaces == 0x8000)
		if((res & 0x10000) != 0)
		  ++res;
	  s32 final = (res >> 16);
	  if(final > 32767) final = 32767;
	  else if(final < -32768) final = -32768;
	  prev2 = prev1;
	  prev1 = final;
	  *destChannel1 = (s16)final;
	  destChannel1 += delta;
	}

	thpAudioInitialize(s, srcChannel2);//XXX
	prev1 = VideoBE16(srcBuffer+76);//XXX
	prev2 = VideoBE16(srcBuffer+78);//XXX
	for(u32 j = 0; j < numSamples; ++j)
	{
	  s64 res = (s64)thpAudioGetNewSample(s);
	  res = (res * ((s64)1 << (s.shift+11)));
	  s64 val1 = table2[2*s.index];//XXX
	  s64 val2 = table2[2*s.index + 1];//XXX
	  res = (val1*prev1 + val2*prev2 + res) * 32;
	  u16 decimalPlaces = res & 0xffff;
	  if(decimalPlaces > 0x8000)
		++res;
	  else if(decimalPlaces == 0x8000)
		if((res & 0x10000) != 0)
		  ++res;
	  s32 final = (res >> 16);
	  if(final > 32767) final = 32767;
	  else if(final < -32768) final = -32768;
	  prev2 = prev1;
	  prev1 = final;
	  *destChannel2 = (s16)final;
	  destChannel2 += delta;
	}
  }

  return numSamples;
}


VideoFrame::VideoFrame()
: _data(NULL), _w(0), _h(0), _p(0)
{}

VideoFrame::~VideoFrame()
{ dealloc(); }

bool VideoFrame::resize(int width,int height)
{
    if(width<=0 || height<=0 || width>1024 || height>1024) return false;
    if(width==_w && height==_h && _data) return true;
    int pitch=(3*width+3)&~3;
    u8 *staged=new(std::nothrow) u8[pitch*height];
    WX_MEMORY_ALLOC(CPU,WX_MEM_MOVIE_RGB,staged,pitch*height);
    if(!staged) return false;
    dealloc();_w=width;_h=height;_p=pitch;_data=staged;return true;
}

void VideoFrame::dealloc()
{
  if(_data != NULL) {
    WX_MEMORY_FREE(CPU,WX_MEM_MOVIE_RGB,_data,_p*_h);
    delete [] _data;
  }
  _data = NULL;
  _w = _h = _p = 0;
}

//swaps red and blue channel of a video frame
void swapRB(VideoFrame& f)
{
  u8* currLine = f.getData();

  int hyt = f.getHeight();
  int pitch = f.getPitch();

  for(int y = 0; y < hyt; ++y)
  {
	for(int x = 0, x2 = 2; x < f.getWidth()*3; x += 3, x2 += 3)
	{
	  u8 t = currLine[x];
	  currLine[x] = currLine[x2];
	  currLine[x2] = t;
	}
	currLine += pitch;
  }
}

enum FILETYPE
{
  THP, MTH, JPG,
	UNKNOWN = -1
};

FILETYPE getFiletype(FILE* f)
{
  long t = ftell(f);
  fseek(f, 0, SEEK_SET);

  u8 buff[4];
  if(fread(buff,1,4,f)!=4 || ferror(f)) return UNKNOWN;

  FILETYPE ret = UNKNOWN;
  if(memcmp("THP\0", buff, 4) == 0)
	ret = THP;
  else if(memcmp("MTHP", buff, 4) == 0)
	ret = MTH;
  else if(buff[0] == 0xff && buff[1] == 0xd8)
	ret = JPG;

  fseek(f, t, SEEK_SET);
  return ret;
}

long getFilesize(FILE* f)
{
  long t = ftell(f);
  fseek(f, 0, SEEK_END);
  long ret = ftell(f);
  fseek(f, t, SEEK_SET);
  return ret;
}

VideoFile::VideoFile(FILE* f)
: _f(f),_valid(false),_fileSize(0),_budget(WxMemoryBudget())
{
    struct stat st;if(f && fstat(fileno(f),&st)==0 && st.st_size>=0) _fileSize=st.st_size;
}

VideoFile::~VideoFile()
{
  if(_f != NULL)
	fclose(_f);
  _f = NULL;
}


//as mentioned above, we have to convert 0xff to 0xff 0x00
//after the image date has begun (ie, after the 0xff 0xda marker)
//but we must not convert the end-of-image-marker (0xff 0xd9)
//this way. There may be 0xff 0xd9 bytes embedded in the image
//data though, so I add 4 bytes to the input buffer
//and fill them with zeroes and check for 0xff 0xd9 0 0
//as end-of-image marker. this is not correct, but works
//and is easier to code... ;-)
//a better solution would be to patch jpeglib so that this conversion
//is not neccessary

u8 endBytesThp[] = { 0xff, 0xd9, 0, 0 }; //used in thp files
u8 endBytesMth[] = { 0xff, 0xd9, 0xff, 0 }; //used in mth files

static inline int convertToRealJpeg(u8* dest, const u8* src, int srcSize)
{
  if(!dest || !src || srcSize<3) return 0;
  int start, end = 0;

  int j;
  for(j = srcSize - 1; (j > 2) && (src[j] == 0); --j)
	; //search end of data

  if(src[j] == 0xd9) //thp file
	end = j - 1;
  else if(src[j] == 0xff) //mth file
	end = j - 2;

  // set maxed out value
  start = end;

  int di = 0;
  for(int i = 0; i < srcSize; ++i, ++di)
  {
	dest[di] = src[i];
	//if i == srcSize - 1, then this would normally overrun src - that's why 4 padding
	//bytes are included at the end of src
	if(src[i] == 0xff)
	{
		if((start == end) && (i < srcSize-2) && (src[i + 1] == 0xda))
		  start = i;

		if(i > start && i < end)
		{
		  ++di;
		  dest[di] = 0;
		}
	}
  }
  return di;
}

void decodeRealJpeg(const u8* data, int size, VideoFrame& dest);
static void decodeJpegFile(FILE *,VideoFrame &);

void VideoFile::loadFrame(VideoFrame& frame, const u8* data, int size) const
{
  const u8 *buff = data;

  if(!data || size<=0) { frame.dealloc();return; }
  if(!_decodeBuffer.empty())
  {
      if((size_t)size>_decodeBuffer.size()/2) { frame.dealloc();return; }
	  //convert format so jpeglib understands it...
	  size = convertToRealJpeg((u8 *)&_decodeBuffer[0], buff, size);
	  buff = &_decodeBuffer[0];
  }

  //...and feed it to jpeglib
  decodeRealJpeg(buff, size, frame);
}


ThpVideoFile::ThpVideoFile(FILE *f):VideoFile(f)
{
    memset(&_head,0,sizeof(_head));memset(&_components,0,sizeof(_components));
    memset(&_videoInfo,0,sizeof(_videoInfo));memset(&_audioInfo,0,sizeof(_audioInfo));
    _currFrameNr=-1;_nextFrameOffset=0;_nextFrameSize=0;_numInts=3;
    if(!readThpHeader(f,_head) || memcmp(_head.tag,"THP\0",4) ||
       (_head.version!=0x00010000 && _head.version!=0x00011000) ||
       !_head.numFrames || _head.numFrames>INT_MAX || !std::isfinite(_head.fps) || _head.fps<1 || _head.fps>240 ||
       !_head.maxBufferSize || _head.maxBufferSize>_budget/4 || _head.maxBufferSize>INT_MAX/2 ||
       _head.componentDataOffset>_fileSize || fseeko(f,_head.componentDataOffset,SEEK_SET)!=0 ||
       !readThpComponents(f,_components) || !_components.numComponents || _components.numComponents>16) return;
    for(u32 i=0;i<_components.numComponents;++i) {
        if(_components.componentTypes[i]==0) { if(!readThpVideoInfo(f,_videoInfo,_head.version==0x00011000)) return; }
        else if(_components.componentTypes[i]==1) { if(!readThpAudioInfo(f,_audioInfo,_head.version==0x00011000)) return; }
        else return;
    }
    if(!_videoInfo.width || !_videoInfo.height || _videoInfo.width>1024 || _videoInfo.height>1024) return;
    if(_head.maxAudioSamples) {
        if(_audioInfo.numChannels<1 || _audioInfo.numChannels>2 || !_audioInfo.frequency || _audioInfo.frequency>48000 ||
           _audioInfo.numData!=1 || _head.maxAudioSamples>INT_MAX/(2*_audioInfo.numChannels*8)) return;
        _numInts=4;
    }
    _nextFrameOffset=_head.firstFrameOffset;_nextFrameSize=_head.firstFrameSize;
    try { _decodeBuffer.resize((size_t)_head.maxBufferSize*2); }
    catch(const std::bad_alloc &) { return; }
    _valid=true;loadNextFrame();
}

void ThpVideoFile::loadNextFrame()
{
  if(!_valid) return;
  ++_currFrameNr;
  if(_currFrameNr >= (int) _head.numFrames)
  {
	_currFrameNr = 0;
	_nextFrameOffset = _head.firstFrameOffset;
	_nextFrameSize = _head.firstFrameSize;
  }

  if(!_valid || _nextFrameSize<(u32)_numInts*4 || _nextFrameSize>_head.maxBufferSize ||
     _nextFrameOffset>_fileSize || _nextFrameSize>_fileSize-_nextFrameOffset ||
     fseeko(_f,_nextFrameOffset,SEEK_SET)!=0) { _valid=false;_currFrameData.clear();return; }
  try { _currFrameData.resize(_nextFrameSize); } catch(const std::bad_alloc &) { _valid=false;return; }
  if(fread(_currFrameData.data(),1,_nextFrameSize,_f)!=_nextFrameSize || ferror(_f)) { _valid=false;_currFrameData.clear();return; }
  _nextFrameOffset+=_nextFrameSize;_nextFrameSize=VideoBE32(_currFrameData.data());
}

void ThpVideoFile::getCurrentFrame(VideoFrame& f) const
{
	decodeVideoFrame(f, _currFrameData);
}

void ThpVideoFile::decodeVideoFrame(VideoFrame& f, const std::vector<u8> &frameBuffer) const
{
    size_t header=(size_t)_numInts*4;
    if(frameBuffer.size()<header) { f.dealloc();return; }
    u32 bytes=VideoBE32(frameBuffer.data()+8);
    if(bytes>INT_MAX || bytes>frameBuffer.size()-header) { f.dealloc();return; }
    loadFrame(f,frameBuffer.data()+header,bytes);
}

int ThpVideoFile::getNumChannels() const
{
  if(hasSound())
	return _audioInfo.numChannels;
  else
	return 0;
}

int ThpVideoFile::getFrequency() const
{
  if(hasSound())
	return _audioInfo.frequency;
  else
	return 0;
}

int ThpVideoFile::getCurrentBuffer(s16* data) const
{
  if(!hasSound())
	return 0;

  size_t header=(size_t)_numInts*4;
  if(!data || _currFrameData.size()<header) return 0;
  u32 jpegSize=VideoBE32(_currFrameData.data()+8);
  if(jpegSize>_currFrameData.size()-header) return 0;
  const u8 *src=_currFrameData.data()+header+jpegSize;
  size_t bytes=_currFrameData.size()-header-jpegSize;
  if(bytes<80) return 0;
  u32 channel=VideoBE32(src),samples=VideoBE32(src+4);
  if(samples>_head.maxAudioSamples || channel>bytes-80 ||
     (_audioInfo.numChannels==2 && channel>(bytes-80)/2) ||
     ((u64)samples+13)/14*8>channel) return 0;
  return thpAudioDecode(data,src,false,_audioInfo.numChannels==2);
}

MthVideoFile::MthVideoFile(FILE *f):VideoFile(f)
{
    memset(&_head,0,sizeof(_head));_currFrameNr=-1;_nextFrameOffset=0;_nextFrameSize=_thisFrameSize=0;
    if(!readMthHeader(f,_head) || memcmp(_head.tag,"MTHP",4) || !_head.numFrames || _head.numFrames>INT_MAX ||
       !_head.width || !_head.height || _head.width>1024 || _head.height>1024 || !_head.fps || _head.fps>240 ||
       !_head.maxFrameSize || _head.maxFrameSize>_budget/4 || _head.maxFrameSize>INT_MAX/2) return;
    _nextFrameOffset=_head.offset;_nextFrameSize=_head.firstFrameSize;
    try { _decodeBuffer.resize((size_t)_head.maxFrameSize*2); } catch(const std::bad_alloc &) { return; }
    _valid=true;loadNextFrame();
}

void MthVideoFile::loadNextFrame()
{
  if(!_valid) return;
  ++_currFrameNr;
  if(_currFrameNr >= (int) _head.numFrames)
  {
	_currFrameNr = 0;
	_nextFrameOffset = _head.offset;
	_nextFrameSize = _head.firstFrameSize;
  }

  if(_nextFrameSize<4 || _nextFrameSize>_head.maxFrameSize || _nextFrameOffset>_fileSize ||
     _nextFrameSize>_fileSize-_nextFrameOffset || fseeko(_f,_nextFrameOffset,SEEK_SET)!=0) { _valid=false;_currFrameData.clear();return; }
  try { _currFrameData.resize(_nextFrameSize); } catch(const std::bad_alloc &) { _valid=false;return; }
  if(fread(_currFrameData.data(),1,_nextFrameSize,_f)!=_nextFrameSize || ferror(_f)) { _valid=false;_currFrameData.clear();return; }
  _thisFrameSize=_nextFrameSize;_nextFrameOffset+=_nextFrameSize;
  _nextFrameSize=VideoBE32(_currFrameData.data());

}

void MthVideoFile::getCurrentFrame(VideoFrame& f) const
{
	decodeVideoFrame(f, _currFrameData);
}

void MthVideoFile::decodeVideoFrame(VideoFrame& f, const std::vector<u8> &frameBuffer) const
{
  if(frameBuffer.size()<4 || frameBuffer.size()>INT_MAX) { f.dealloc();return; }
  loadFrame(f,frameBuffer.data()+4,frameBuffer.size()-4);
}

JpgVideoFile::JpgVideoFile(FILE* f)
: VideoFile(f)
{
  decodeJpegFile(f,_currFrame);_valid=_currFrame.getData()!=NULL;
}

void JpgVideoFile::getCurrentFrame(VideoFrame& f) const
{
  if(!f.resize(_currFrame.getWidth(),_currFrame.getHeight())) { f.dealloc();return; }
  memcpy(f.getData(), _currFrame.getData(),f.getPitch()*f.getHeight());
}

void JpgVideoFile::decodeVideoFrame(VideoFrame& f, const std::vector<u8> &frameBuffer UNUSED) const
{
	getCurrentFrame(f);
}

VideoFile* openVideo(const string& fileName)
{
  FILE* f = fopen(fileName.c_str(), "rb");
  if(f == NULL)
	return NULL;

  FILETYPE type=getFiletype(f);VideoFile *video=NULL;
  // Constructors consume/close f through their base once construction starts.
  switch(type) {
    case THP: video=new(std::nothrow) ThpVideoFile(f);break;
    case MTH: video=new(std::nothrow) MthVideoFile(f);break;
    case JPG: video=new(std::nothrow) JpgVideoFile(f);break;
    default: fclose(f);return NULL;
  }
  if(!video) { fclose(f);return NULL; }
  if(!video->valid()) { delete video;return NULL; }
  return video;
}

void closeVideo(VideoFile*& vf)
{
  if(vf != NULL)
	delete vf;
  vf = NULL;
}

extern "C"
{
#include "jpeglib.h"
#include <setjmp.h>
}

//the following functions are needed to let
//libjpeg read from memory instead of from a file...
//it's a little clumsy to do :-|
struct MovieJpegError { jpeg_error_mgr base; jmp_buf jump; };
static void MovieJpegExit(j_common_ptr cinfo)
{
    longjmp(((MovieJpegError*)cinfo->err)->jump,1);
}
static void MovieJpegMessage(j_common_ptr cinfo,int level) { if(level<0) ++cinfo->err->num_warnings; }
static void DecodeJpeg(const u8 *data,int size,FILE *file,VideoFrame &dest)
{
    if(!file && (!data || size<=0)) { dest.dealloc();return; }
    jpeg_decompress_struct cinfo={};MovieJpegError error={};
    volatile bool created=false;
    cinfo.err=jpeg_std_error(&error.base);error.base.error_exit=MovieJpegExit;error.base.emit_message=MovieJpegMessage;
    if(setjmp(error.jump)) {
        if(created) jpeg_destroy_decompress(&cinfo);
        dest.dealloc();return;
    }
    jpeg_create_decompress(&cinfo);created=true;
    // libjpeg v8 declares this input mutable, although it only reads it.
    if(file) jpeg_stdio_src(&cinfo,file);else jpeg_mem_src(&cinfo,const_cast<u8 *>(data),size);
    bool okay=jpeg_read_header(&cinfo,TRUE)==JPEG_HEADER_OK;
    okay=okay && cinfo.image_width>0 && cinfo.image_height>0 && cinfo.image_width<=1024 && cinfo.image_height<=1024;
    if(okay) {
        cinfo.do_fancy_upsampling=FALSE;cinfo.do_block_smoothing=FALSE;
        cinfo.out_color_space=JCS_RGB;cinfo.quantize_colors=FALSE;
        cinfo.scale_num=cinfo.scale_denom=1;cinfo.dct_method=JDCT_FASTEST;
        okay=jpeg_start_decompress(&cinfo) && cinfo.output_components==3 &&
             dest.resize(cinfo.output_width,cinfo.output_height);
        while(okay && cinfo.output_scanline<cinfo.output_height) {
            u8 *row=dest.getData()+cinfo.output_scanline*dest.getPitch();
            okay=jpeg_read_scanlines(&cinfo,&row,1)==1;
        }
        if(okay) okay=jpeg_finish_decompress(&cinfo) && !cinfo.err->num_warnings;
    }
    jpeg_destroy_decompress(&cinfo);
    if(!okay) dest.dealloc();
}
void decodeRealJpeg(const u8 *data,int size,VideoFrame &dest) { DecodeJpeg(data,size,NULL,dest); }
static void decodeJpegFile(FILE *file,VideoFrame &dest) { DecodeJpeg(NULL,0,file,dest); }
