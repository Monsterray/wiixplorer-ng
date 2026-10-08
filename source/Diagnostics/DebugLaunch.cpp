#include "DebugLaunch.h"
#if WX_DEBUG_BUILD
#include <stdio.h>
#include <string.h>

bool DebugBenchArgument(DebugBenchArguments &args,const char *line)
{
    if(!line) return false;
    static const char *options[]={"--memory-bench=","--archive-check=","--archive-output=","--copy-bench=","--storage-bench=","--storage-report=","--media-bench=","--features-bench="};
    for(unsigned i=0;i<BenchOptions;++i) {
        size_t prefix=strlen(options[i]);
        if(strncmp(line,options[i],prefix)) continue;
        const char *value=line+prefix; size_t length=strlen(value);
        if(!length || length>=sizeof(args.paths[i]) || args.paths[i][0]) return false;
        for(size_t j=0;j<length;++j) if((unsigned char)value[j]<32 || (unsigned char)value[j]==127) return false;
        memcpy(args.paths[i],value,length+1);
        return true;
    }
    return false;
}
bool DebugBenchFile(DebugBenchArguments &args,const char *file)
{
    FILE *f=fopen(file,"rb"); if(!f) return false;
    DebugBenchArguments staged=args; char line[800]; unsigned lines=0; bool okay=true;
    while(okay && fgets(line,sizeof(line),f)) {
        size_t length=strlen(line);
        if(++lines>BenchOptions || !length || line[length-1]!='\n') { okay=false; break; }
        line[--length]=0;
        if(length && line[length-1]=='\r') line[--length]=0;
        okay=DebugBenchArgument(staged,line);
    }
    okay=okay && lines && !ferror(f);
    if(fclose(f)!=0) okay=false;
    if(okay) args=staged; // Malformed/truncated config never partly enables tests.
    return okay;
}
#endif
