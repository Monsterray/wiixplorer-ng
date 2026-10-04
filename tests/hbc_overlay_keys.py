#!/usr/bin/env python3
"""The real SDK queue must retain keys while opening/closing animation drops input."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
files=list((ROOT/'.deps/work/hbc-agent').glob('*/sdk/hbc_agent/overlay.c'))
if not files:
 print('HBC overlay input check skipped: build SDK first');raise SystemExit(0)
s=files[0].read_text();start=s.index('static unsigned read_input(');end=s.index('// GameCube controllers',start)
production=s[start:end]+'return out;\n}\n'
assert 'pressed = read_input(ui.open_t == 256 && !ui.closing);' in s
code=r'''
#include <cassert>
using u32=unsigned;
enum {OV_UP=1,OV_DOWN=2,OV_LEFT=4,OV_RIGHT=8,OV_A=16,OV_B=32,OV_HOME=64,OV_1=128,OV_2=256,OV_WAV=512,OV_ANY=1024};
struct {int open_t;bool closing;} ui;
int key='r',pops=0;
int agent_key_pop(){++pops;int k=key;key=0;return k;}
'''+production+r'''
int main(){
 for(int frame=0;frame<16;++frame){ui.open_t=frame*16;assert(read_input(ui.open_t==256 && !ui.closing)==0);assert(key=='r' && !pops);}
 ui.open_t=256;assert(read_input(ui.open_t==256 && !ui.closing)==(OV_RIGHT|OV_ANY));assert(!key && pops==1);
 key='a';for(int frame=0;frame<12;++frame)assert(!read_input(ui.open_t==256 && !ui.closing));
 ui.closing=true;for(int frame=0;frame<16;++frame)assert(!read_input(ui.open_t==256 && !ui.closing));assert(key=='a');
 ui.closing=false;assert(read_input(ui.open_t==256 && !ui.closing)==(OV_A|OV_ANY));
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('HBC queued navigation: opening/closing retains presses; settled UI consumes paced keys')
# Compile the upstream portable UI itself; both app callbacks must run and no
# exit action may fire, including when adjacent presses are only one frame apart.
ui_code=r'''
#include "ov_ui.h"
#include <assert.h>
#include <string.h>
static unsigned callbacks[2];
static void act(int action,int arg,void *user){(void)user;assert(action>OVA_POWEROFF);if(action==OVA_SLOT_ITEM){assert(arg==0 || arg==16);++callbacks[arg/16];}}
static void press(ov_ui *ui,ov_ext *ext,unsigned key,int gap){assert(ov_step(ui,ext,key,act,0));for(int i=0;i<gap;++i)assert(ov_step(ui,ext,0,act,0));}
int main(void){
 for(int gap=1;gap<=45;gap+=11){
  ov_ui ui;ov_ext ext={0};callbacks[0]=callbacks[1]=0;
  strcpy(ext.slot[0],"Settings");strcpy(ext.slot[1],"Diagnostics");ext.exit_mask=15;
  for(int i=0;i<2;++i){ext.menu[i].count=1;strcpy(ext.menu[i].item[0].label,"Callback");}
  ov_init(&ui,640,480);for(int i=0;i<32;++i)assert(ov_step(&ui,&ext,0,act,0));
  press(&ui,&ext,OV_LEFT,gap);press(&ui,&ext,OV_A,gap);press(&ui,&ext,OV_A,gap);
  press(&ui,&ext,OV_B,gap);press(&ui,&ext,OV_RIGHT,gap);press(&ui,&ext,OV_RIGHT,gap);
  press(&ui,&ext,OV_A,gap);press(&ui,&ext,OV_A,gap);
  assert(callbacks[0]==1 && callbacks[1]==1);
 }
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'test.c').write_text(ui_code);agent=files[0].parent
 subprocess.run([os.environ.get('CC','cc'),'-std=c99','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(agent),str(p/'test.c'),str(agent/'ov_ui.c'),str(agent/'ov_draw.c'),'-o',str(p/'test')]+([] if os.name=='nt' else ['-lm']),check=True)
 subprocess.run([str(p/'test')],check=True)
print('Real HBC portable UI: Settings/Back/Diagnostics callbacks, varied frame gaps, no unintended exit')
