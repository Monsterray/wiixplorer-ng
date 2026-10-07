/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "TransferBench.h"
#if WX_DEBUG_BUILD
#include "Diagnostics/MemoryProbes.h"
#include "ImageOperations/GifImage.hpp"
#include "ImageOperations/TplImage.h"
#include "ImageOperations/TextureConverter.h"
#include "VideoOperations/gcvid.h"
#include "VideoOperations/WiiMovie.hpp"
#include "TextOperations/PDFViewer.hpp"
#include "Controls/Application.h"
#include "Tools/BufferCircle.hpp"

#include <ogc/lwp_watchdog.h>
#include <sys/stat.h>
#include <stdio.h>
#include <string.h>
#include <new>
#include <algorithm>
extern "C" {
#include <jpeglib.h>
}
static void MediaWord(u8 *p,u32 word) { p[0]=word>>24;p[1]=word>>16;p[2]=word>>8;p[3]=word; }
static bool MediaJpeg(const char *path,unsigned width=5,unsigned height=3,bool red=false)
{
    FILE *f=fopen(path,"wb");if(!f) return false;
    jpeg_compress_struct c={};jpeg_error_mgr error={};c.err=jpeg_std_error(&error);
    // Valid, fixed, tiny encoder fixture; no untrusted dimensions or input.
    jpeg_create_compress(&c);jpeg_stdio_dest(&c,f);
    c.image_width=width;c.image_height=height;c.input_components=3;c.in_color_space=JCS_RGB;
    jpeg_set_defaults(&c);jpeg_start_compress(&c,TRUE);
    u8 white[320*3];memset(white,255,sizeof(white));
    if(red) for(unsigned i=0;i<320;++i) white[i*3+1]=white[i*3+2]=0;
    while(c.next_scanline<c.image_height) { u8 *row=white;jpeg_write_scanlines(&c,&row,1); }
    jpeg_finish_compress(&c);jpeg_destroy_compress(&c);
    return fclose(f)==0;
}
static bool MediaMth(const char *jpeg,const char *path)
{
    std::vector<u8> frames[2];
    for(unsigned color=0;color<2;++color) {
        if(!MediaJpeg(jpeg,320,240,color!=0)) return false;
        FILE *in=fopen(jpeg,"rb");if(!in) return false;
        std::vector<u8> encoded(65536);size_t n=fread(encoded.data(),1,encoded.size(),in);
        bool okay=n>4 && n<encoded.size() && !ferror(in);if(fclose(in)!=0) okay=false;
        if(remove(jpeg)!=0 || !okay) return false;
        encoded.resize(n);frames[color].reserve(n);
        size_t entropy=n;
        for(size_t i=0;i+3<n;++i) if(encoded[i]==0xff && encoded[i+1]==0xda) {
            entropy=i+2+((unsigned)encoded[i+2]<<8)+encoded[i+3];break;
        }
        if(entropy>=n) return false;
        for(size_t i=0;i<n;++i) { frames[color].push_back(encoded[i]);if(i>=entropy && encoded[i]==0xff && i+1<n && !encoded[i+1]) ++i; }
    }
    u8 header[44]={};memcpy(header,"MTHP",4);
    MediaWord(header+12,std::max(frames[0].size(),frames[1].size())+4);
    MediaWord(header+16,320);MediaWord(header+20,240);
    MediaWord(header+24,30);MediaWord(header+28,30);MediaWord(header+32,44);MediaWord(header+40,frames[0].size()+4);
    FILE *out=fopen(path,"wb");if(!out) return false;
    bool okay=fwrite(header,1,sizeof(header),out)==sizeof(header);
    for(unsigned i=0;i<30 && okay;++i) {
        // Ten-frame color spans permit deterministic observation at either VI rate.
        const std::vector<u8> &frame=frames[(i/10)&1];
        u8 next[4];MediaWord(next,frames[(((i+1)%30)/10)&1].size()+4);
        okay=fwrite(next,1,4,out)==4 && fwrite(frame.data(),1,frame.size(),out)==frame.size();
    }
    return fclose(out)==0 && okay;
}

static bool capturePixel=false;
static GXColor pixel;
void MediaCapturePixel()
{
    if(capturePixel) { GX_DrawDone(); GX_PeekARGB(320,240,&pixel); capturePixel=false; }
}
static bool MediaPixel(bool white)
{
    capturePixel=true;
    Application::Instance()->updateEvents();
    return pixel.r>240 && (white ? pixel.g>240 && pixel.b>240 : pixel.g<16 && pixel.b<16);
}
static bool MediaPdf(const char *path)
{
    FILE *f=fopen(path,"wb");if(!f) return false;
    const char *objects[]={"<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> /Contents 4 0 R >>", "<< /Length 26 >>\nstream\n1 0 0 rg 0 0 612 792 re f\nendstream"};
    long offsets[4];bool okay=fprintf(f,"%%PDF-1.4\n")>0;
    for(unsigned i=0;i<4 && okay;++i) { offsets[i]=ftell(f);okay=offsets[i]>=0 && fprintf(f,"%u 0 obj\n%s\nendobj\n",i+1,objects[i])>0; }
    long xref=ftell(f);okay=okay && xref>=0 && fprintf(f,"xref\n0 5\n0000000000 65535 f \n")>0;
    for(unsigned i=0;i<4 && okay;++i) okay=fprintf(f,"%010ld 00000 n \n",offsets[i])>0;
    okay=okay && fprintf(f,"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n%ld\n%%%%EOF\n",xref)>0;
    return fclose(f)==0 && okay;
}
class MediaPdfViewer : public PDFViewer {
public:
    explicit MediaPdfViewer(const char *path):PDFViewer(path) {}
    bool Ready() { pageMutex.lock();bool ready=OutputImage && imagewidth==612 && imageheight==792;pageMutex.unlock();return ready; }
    void Close() { POINT point={};OnButtonClick(backButton,0,point); }
};
class MediaMovie : public WiiMovie {
public:
    explicit MediaMovie(const char *path):WiiMovie(path) {}
    bool Ready() { return FrameBufCount>0 && !ExitRequested; }
};
void RunMediaValidation(const char *root)
{
    // Only the leased runner's private fixture root; never reuse user storage.
    if(!root || strncmp(root,"sd:/wiixplorer-copy-",19) || strlen(root)>600 || strstr(root,"..") || mkdir(root,0700)!=0) return;
    char report[768],jpeg[768],pdf[768],moviePath[768],complete[768];
    int r=snprintf(report,sizeof(report),"%s/media-results.csv",root);
    int j=snprintf(jpeg,sizeof(jpeg),"%s/media.jpg",root);
    int m=snprintf(moviePath,sizeof(moviePath),"%s/media.mth",root);
    int p=snprintf(pdf,sizeof(pdf),"%s/media.pdf",root);
    int c=snprintf(complete,sizeof(complete),"%s/media-complete",root);
    if(m<=0 || m>=(int)sizeof(moviePath) || p<=0 || p>=(int)sizeof(pdf) || r<=0 || r>=(int)sizeof(report) || j<=0 || j>=(int)sizeof(jpeg) || c<=0 || c>=(int)sizeof(complete)) return;
    FILE *out=fopen(report,"wb");if(!out) return;
    bool okay=fprintf(out,"case,iterations,microseconds,verified,pixel_r,pixel_g,pixel_b\n")>0;
    const char *names[]={"gif_reload","tpl_bounds","jpeg_stream","audio_ring","rgb_stride","pdf_render","movie_workers"};
    for(unsigned group=0;group<7 && okay;++group) {
        WX_MEMORY_SNAPSHOT("media_begin");wx_memory_flush();
        u64 start=gettime();bool verified=true;
        try {
            if(group==0) {
                const u8 gif[]={71,73,70,56,57,97,1,0,1,0,128,0,0,0,0,0,255,255,255,44,0,0,0,0,1,0,1,0,0,2,2,68,1,0,59};
                GifImage image(NULL,0);
                for(unsigned i=0;i<100 && verified;++i) {
                    image.LoadImage(gif,sizeof(gif));verified=image.GetFrameCount()==1 && image.GetFrameImage(0)[0]==255;
                    for(unsigned n=0;n<sizeof(gif) && verified;++n) { image.LoadImage(gif,n);verified=image.GetFrameCount()==0; }
                }
            } else if(group==1) {
                u8 tpl[120]={};MediaWord(tpl,0x0020af30);MediaWord(tpl+4,1);MediaWord(tpl+8,12);MediaWord(tpl+12,20);
                tpl[21]=4;tpl[23]=4;MediaWord(tpl+24,6);MediaWord(tpl+28,56);
                TplImage image(NULL,0);
                for(unsigned i=0;i<100 && verified;++i) {
                    verified=image.LoadImage(tpl,sizeof(tpl)) && image.GetTextureSize(0)==64;
                    for(unsigned n=0;n<sizeof(tpl) && verified;++n) { verified=!image.LoadImage(tpl,n) && image.GetTextureBuffer(0)==NULL; }
                }
            } else if(group==2) {
                verified=MediaJpeg(jpeg);
                for(unsigned i=0;i<100 && verified;++i) {
                    VideoFile *video=openVideo(jpeg);VideoFrame frame;
                    verified=video && video->valid();
                    if(video) { video->getCurrentFrame(frame);verified=verified && frame.getData() && frame.getPitch()==16 && frame.getData()[0]==255;closeVideo(video); }
                }
                if(remove(jpeg)!=0) verified=false;
            } else if(group==3) {
                for(unsigned i=0;i<100 && verified;++i) {
                    BufferCircle ring;
                    verified=ring.SetBufferBlockSize(4096) && ring.Resize(3);
                    if(!verified) break;
                    memset(ring.GetBuffer(),0,4096);ring.SetBufferSize(0,4096);ring.SetBufferReady(0,true);
                    verified=ring.IsBufferReady();ring.LoadNext();ring.LoadNext();
                    verified=verified && ring.Resize(1) && ring.Which()==0 && ring.Resize(0);
                    ring.LoadNext();verified=verified && !ring.GetBuffer();
                }
            } else if(group==4) {
                alignas(32) u8 rgb[3*16],texture[8*4*2];memset(rgb,255,sizeof(rgb));
                for(unsigned i=0;i<100 && verified;++i) {
                    memset(texture,0xa5,sizeof(texture));RGB8ToRGB565Stride(rgb,texture,5,3,16);
                    for(unsigned y=0;y<4;++y) for(unsigned x=0;x<8;++x) {
                        unsigned pixel=((y/4)*2+x/4)*16+(y%4)*4+x%4;
                        u16 value=((u16*)texture)[pixel];
                        if(value!=(x<5 && y<3 ? 0xffff : 0)) verified=false;
                    }
                }
            } else if(group==5) {
                verified=MediaPdf(pdf);
                for(unsigned i=0;i<3 && verified;++i) {
                    MediaPdfViewer *viewer=new MediaPdfViewer(pdf);Application::Instance()->Append(viewer);
                    u64 until=gettime()+secs_to_ticks(5);
                    while(!viewer->Ready() && gettime()<until) Application::Instance()->updateEvents();
                    verified=viewer->Ready();
                    for(unsigned n=0;n<30;++n) Application::Instance()->updateEvents();
                    verified=verified && MediaPixel(false);
                    uintptr_t token=(uintptr_t)viewer;
                    viewer->Close();until=gettime()+secs_to_ticks(5);
                    bool present=true;
                    while(present && gettime()<until) {
                        Application::Instance()->updateEvents();present=false;
                        for(u32 child=0;child<Application::Instance()->GetSize();++child)
                            if((uintptr_t)Application::Instance()->GetGuiElementAt(child)==token) present=true;
                    }
                    verified=verified && !present; // Actual close/fade/delete path.
                }
                if(remove(pdf)!=0) verified=false;
            } else {
                verified=MediaMth(jpeg,moviePath);
                for(unsigned i=0;i<3 && verified;++i) {
                    MediaMovie *movie=new MediaMovie(moviePath);Application::Instance()->Append(movie);
                    verified=movie->Play();u64 until=gettime()+secs_to_ticks(5);
                    while(verified && !movie->Ready() && gettime()<until) Application::Instance()->updateEvents();
                    verified=verified && movie->Ready();
                    for(unsigned n=0;n<30;++n) Application::Instance()->updateEvents();
                    // Observe both colors; a stale single frame must not pass.
                    unsigned colors=0;
                    for(unsigned n=0;n<90 && verified;++n) {
                        bool white=MediaPixel(true);
                        bool red=pixel.r>240 && pixel.g<16 && pixel.b<16;
                        if(white) colors|=1;else if(red) colors|=2;else verified=false;
                    }
                    verified=verified && colors==3;
                    Application::Instance()->Remove(movie);delete movie;
                }
                if(remove(moviePath)!=0) verified=false;
            }
        } catch(const std::bad_alloc &) { verified=false; }
        u64 elapsed=ticks_to_microsecs(gettime()-start);
        okay=fprintf(out,"%s,%u,%llu,%u,%u,%u,%u\n",names[group],group<5 ? 100 : 3,(unsigned long long)elapsed,verified,pixel.r,pixel.g,pixel.b)>0 && fflush(out)==0 && verified;
        WX_MEMORY_SNAPSHOT("media_released");wx_memory_flush();
    }
    if(fclose(out)!=0) okay=false;
    FILE *done=fopen(complete,"wb");if(done) { fputc(okay ? '1' : '0',done);fclose(done); }
}
#endif
