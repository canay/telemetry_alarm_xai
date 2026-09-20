"""Isolate watchdog thread; synthetic fixture only.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
"""
import sys,time,json,subprocess,threading,os
from pathlib import Path
import psutil
if len(sys.argv)>1:
 parent=int(sys.argv[1]); born=float(sys.argv[2]); log=Path(sys.argv[3])
 def note(s):
  with log.open('a') as f: f.write(json.dumps({'at':time.monotonic(),'note':s})+'\n')
 def watcher():
  note('thread_enter')
  while True:
   time.sleep(.1)
   note('before_create_time')
   try: live=psutil.Process(parent).create_time()==born
   except psutil.NoSuchProcess: live=False
   note({'live':live})
   if not live:
    note('before_children')
    children=psutil.Process().children(recursive=True)
    note({'children':len(children)})
    for c in children: c.kill()
    note('before_exit'); os._exit(74)
 threading.Thread(target=watcher,daemon=True).start()
 start=time.monotonic(); checksum=0
 while time.monotonic()-start<5: checksum=(checksum*1103515245+12345)%(2**31)
 note('completed_main')
else:
 r=Path(__file__).parent/'WATCHDOG_PROBE.jsonl'
 assert not r.exists()
 p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
 c=subprocess.Popen([sys.executable,__file__,str(p.pid),str(psutil.Process(p.pid).create_time()),str(r)],
     stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  time.sleep(.4); p.kill(); p.wait(timeout=5)
  out,err=c.communicate(timeout=8)
  print(json.dumps({'rc':c.returncode,'out':out,'err':err,'trace':r.read_text()}))
 finally:
  for proc in (c,p):
   if proc.poll() is None: proc.kill()
   proc.wait(timeout=5)
