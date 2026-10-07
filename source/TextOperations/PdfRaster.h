/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <math.h>
#include <limits.h>
#include <stddef.h>
// Check floating bounds before MuPDF rounds them into signed integers.
inline bool WxPdfRaster(float x0,float y0,float x1,float y1,size_t budget,int &w,int &h)
{
    if(!isfinite(x0) || !isfinite(y0) || !isfinite(x1) || !isfinite(y1) ||
       x0<(double)INT_MIN+2 || y0<(double)INT_MIN+2 ||
       x1>(double)INT_MAX-2 || y1>(double)INT_MAX-2) return false;
    double width=ceil((double)x1)-floor((double)x0),height=ceil((double)y1)-floor((double)y0);
    if(width<=0 || height<=0 || width>1024 || height>1024) return false;
    int nextW=((int)width+3)&~3,nextH=((int)height+3)&~3;
    // RGB-alpha pixmap and RGB565 texture coexist. Library metadata is extra.
    if((size_t)nextW*nextH>budget/6) return false;
    w=nextW;h=nextH;return true;
}
