/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "TransferBench.h"
#if WX_DEBUG_BUILD
#include "Controls/Application.h"
#include "FileOperations/fileops.h"
#include "FileOperations/MD5.h"
#include "ImageOperations/ImageConverter.hpp"
#include "ImageOperations/Screenshot.h"
#include "TextOperations/TextEditor.h"
#include <sys/stat.h>
#include <stdio.h>
#include <string.h>
#include <new>

static bool FeatureContents(const char *path,const char *expected)
{
    FILE *f=fopen(path,"rb");if(!f) return false;
    char content[128];size_t got=fread(content,1,sizeof(content),f);
    bool okay=!ferror(f) && got==strlen(expected) && !memcmp(content,expected,got);
    if(fclose(f)!=0) okay=false;return okay;
}
void RunFeatureValidation(const char *root)
{
    if(!root || strncmp(root,"sd:/wiixplorer-copy-",19) || strlen(root)>600 || strstr(root,"..") || mkdir(root,0700)!=0) return;
    char report[768],complete[768],imagePath[768],textPath[768],copyPath[768];
    const char *suffixes[]={"features-results.csv","features-complete","image","text","copy"};
    char *paths[]={report,complete,imagePath,textPath,copyPath};
    for(unsigned i=0;i<5;++i) { int n=snprintf(paths[i],768,"%s/%s",root,suffixes[i]);if(n<0 || n>=768) return; }
    FILE *out=fopen(report,"wb");if(!out) return;
    bool okay=fprintf(out,"case,verified\n")>0;
    const char *names[]={"png","jpeg","gif","tiff","bmp","gd","gd2","height_resize_flip","screenshot_png","text_utf8","md5_copy_rename_delete"};
    for(unsigned i=0;i<11 && okay;++i) {
        bool verified=false;
        try {
            if(i<8) {
                gdImagePtr source=gdImageCreateTrueColor(5,3);
                if(source) {
                    gdImageFilledRectangle(source,0,0,4,2,gdTrueColor(255,0,0));
                    verified=WriteGDImage(imagePath,source,i<7 ? i : IMAGE_PNG,0);
                    gdImageDestroy(source);
                }
                if(verified) {
                    ImageConverter converter(imagePath);gdImagePtr decoded=converter.GetImagePtr();
                    verified=decoded && gdImageSX(decoded)==5 && gdImageSY(decoded)==3;
                    if(i==7 && verified) {
                        verified=converter.ResizeImage(5,7);decoded=converter.GetImagePtr();
                        verified=verified && gdImageSX(decoded)==5 && gdImageSY(decoded)==7;
                        converter.FlipHorizontal();converter.FlipVertical();
                        verified=verified && gdImageRed(decoded,gdImageGetPixel(decoded,2,3))>240;
                    }
                }
            } else if(i==8) {
                Application::Instance()->updateEvents();
                verified=Screenshot(imagePath,IMAGE_PNG);
                if(verified) { ImageConverter image(imagePath);verified=image.GetImagePtr()!=NULL; }
            } else if(i==9) {
                TextEditor editor(textPath);editor.SetText(L"first line\n\u03a9\n");editor.WriteTextFile(textPath);
                verified=FeatureContents(textPath,"first line\n\xce\xa9\n");
            } else {
                FILE *f=fopen(textPath,"wb");verified=f && fclose(f)==0;
                unsigned char digest[16];char hex[33];
                verified=verified && MD5fromFile(digest,textPath) && !strcmp(MD5ToString(digest,hex),"D41D8CD98F00B204E9800998ECF8427E");
                f=fopen(textPath,"wb");if(f) { verified=verified && fwrite("abc",1,3,f)==3;if(fclose(f)!=0) verified=false; }else verified=false;
                verified=verified && MD5fromFile(digest,textPath) && !strcmp(MD5ToString(digest,hex),"900150983CD24FB0D6963F7D28E17F72");
                ResetReplaceChoice();verified=verified && CopyFile(textPath,copyPath)==1 && FeatureContents(copyPath,"abc");
                remove(textPath);verified=verified && RenameFile(copyPath,textPath) && FeatureContents(textPath,"abc") && RemoveFile(textPath);
            }
        } catch(const std::bad_alloc &) { verified=false; }
        remove(imagePath);remove(textPath);remove(copyPath);
        okay=fprintf(out,"%s,%u\n",names[i],verified)>0 && fflush(out)==0 && verified;
    }
    if(fclose(out)!=0) okay=false;
    FILE *done=fopen(complete,"wb");if(done) { fputc(okay ? '1' : '0',done);fclose(done); }
}
#endif
