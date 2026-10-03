from PIL import Image,ImageChops,ImageStat
from pathlib import Path
import json
import sys
folder=Path(sys.argv[1])
files=sorted(folder.glob('framedump_*.png'),key=lambda p:int(p.stem.split('_')[-1]))
assert len(files)>=120,'Need at least 120 captured frames'
previous=None
bad=[]
maximum=0
for f in files[:-30]:
 n=int(f.stem.split('_')[-1])
 if n<120: continue  # Exclude the intentional startup fade.
 im=Image.open(f).convert('RGB').resize((160,120))
 # Ignore the pointer/clock/taskbar along the bottom; compare the static browser.
 im=im.crop((15,15,145,95))
 if previous is not None:
  delta=sum(ImageStat.Stat(ImageChops.difference(im,previous)).mean)/3
  maximum=max(maximum,delta)
  if delta>20: bad.append((f.name,round(delta,2)))
 previous=im
print(json.dumps({'frames':len(files),'maximum_browser_frame_delta':round(maximum,3),'flashes_or_corruption':bad[:20]}))
assert not bad,'Unexpected full-frame brightness/corruption change after startup'
