#!/usr/bin/env python3
"""Production image/PDF publication and close-with-pending-image regression."""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
def function(path, signature):
    source=(root/path).read_text();start=source.index(signature);end=source.index('{',start)+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
code=r'''
#include <atomic>
#include <cassert>
#include <cstdlib>
#include <ctime>
#include <new>
#include <queue>
#include <mutex>
#include <thread>
#include <unistd.h>
using u8=unsigned char;using u32=unsigned;
const int EFFECT_FADE=1,GX_TF_RGB565=4;
int images=0,deletedWindows=0,baseDraws=0,sets=0;
struct GuiImageData{GuiImageData(u8*,u32){++images;}~GuiImageData(){--images;}void*GetImage(){return this;}};
struct Image{void SetAlpha(int){}void SetAngle(float){}void SetEffect(int,int){}bool IsAnimated(){return false;}void SetImage(GuiImageData*){++sets;}void SetImage(u8*,int,int,int){++sets;}};
struct GuiFrame{void Draw(){++baseDraws;}};
struct CMutex{std::mutex m;void lock(){m.lock();}void unlock(){m.unlock();}};
struct ThreadedTask{virtual void Execute()=0;};
struct Application{static Application*Instance(){static Application a;return &a;}void PushForDelete(void*){++deletedWindows;}};
struct{int SlideshowDelay=99,ImageFadeSpeed=5;}Settings;
struct{struct{struct{bool valid=false;}ir;}wpad;}userInput[4];
class ImageViewer:public GuiFrame{public:
 std::atomic<bool>bExitRequested{false},workerFinished{false};bool deleteQueued=false;
 std::atomic<GuiImageData*>newImageData{nullptr};GuiImageData*imageData=nullptr;
 std::queue<ThreadedTask*>threadTasks;CMutex threadMutex;
 time_t SlideShowStart=0;bool isPointerVisible=false,updateAlpha=false,bSlideShowFadeStart=false;int buttonAlpha=255,rotateRight=90,rotateLeft=90;float currentAngle=0;
 Image widget,*image=&widget,*nextButton=&widget,*prevButton=&widget,*zoominButton=&widget,*zoomoutButton=&widget,*backButton=&widget,*slideshowButton=&widget,*rotateLButton=&widget,*rotateRButton=&widget,*trashButton=&widget;
 void OnFinishedImageLoad(u8*,u32);void executeThread();void Draw();void SetEffect(int,int){}void SetStartUpImageSize(){}void NextImage(bool){}
};
'''
for signature in ('void ImageViewer::OnFinishedImageLoad(', 'void ImageViewer::executeThread(', 'void ImageViewer::Draw('):
    code+=function('source/ImageOperations/ImageViewer.cpp',signature)+'\n'
code+=r'''
struct PDFViewer:ImageViewer{
 CMutex pageMutex;std::atomic<bool>pageReady{false};int pageWake=0,loadPage=1,imagewidth=4,imageheight=4;u8 pixels[32],*OutputImage=pixels;
 int PreparePage(int){return 0;}int PageToTexture(){return 32;}void executeThread();void Draw();
};
PDFViewer*active=nullptr;int wakes=0;
void LWP_SemWait(int){if(++wakes>1)active->bExitRequested=true;}
void LWP_SemPost(int){}
'''
for signature in ('void PDFViewer::executeThread(', 'void PDFViewer::Draw('):
    code+=function('source/TextOperations/PDFViewer.cpp',signature)+'\n'
code+=r'''
int main(){
 ImageViewer v;v.OnFinishedImageLoad((u8*)malloc(4),4);assert(images==1 && sets==0);
 v.Draw();assert(images==1 && sets==1 && !v.newImageData.load());
 v.OnFinishedImageLoad((u8*)malloc(4),4);assert(images==2);
 // A second callback waits for the pending slot, then close must release it.
 std::thread producer([&]{v.OnFinishedImageLoad((u8*)malloc(4),4);});
 usleep(10000);v.bExitRequested=true;producer.join();assert(images==2);
 v.executeThread();assert(v.workerFinished && deletedWindows==0);
 int before=baseDraws;v.Draw();v.Draw();assert(deletedWindows==1 && baseDraws==before+2);
 delete v.newImageData.exchange(nullptr);delete v.imageData;assert(images==0);
 sets=0;PDFViewer pdf;active=&pdf;pdf.executeThread();assert(pdf.workerFinished && pdf.pageReady && sets==0);
 pdf.bExitRequested=false;pdf.Draw();pdf.Draw();assert(sets==1 && !pdf.pageReady);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-image-publish-') as directory:
    tmp=Path(directory);(tmp/'test.cpp').write_text(code)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-pthread','-fsanitize=address,undefined',str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True,timeout=10)
print('Image/PDF publication: render-thread handoff, pending close, worker completion and one delete passed')
