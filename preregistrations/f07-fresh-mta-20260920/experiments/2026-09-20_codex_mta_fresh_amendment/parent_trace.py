"""Timestamped synthetic parent-loss trace; no scientific code.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
"""
import json, subprocess, sys, time
import psutil
import mta_supervisor as a
r=a.BASE/'mta_parent_trace_20260920'; r.mkdir(exist_ok=False)
start=time.monotonic(); rows=[]
def trace(phase,**kw): rows.append({'t':time.monotonic()-start,'phase':phase,**kw})
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
born=psutil.Process(p.pid).create_time(); trace('parent',pid=p.pid,born=born)
command=[str(a.BASE/'supervisor_fixture_worker.py'),'--unit','fixture_0','--output',str(r/'output.json')]
c=subprocess.Popen([sys.executable,str(a.BASE/'fresh_owned_worker.py'),'--parent-pid',str(p.pid),
 '--parent-born',str(born),'--ticket',str(r/'ticket'),'--launch-id','trace','--',*command],
 stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
 a.original.atomic(r/'ticket',{'pid':c.pid,'process_created_at':psutil.Process(c.pid).create_time(),
   'launch_id':'trace','command':command})
 trace('ticket',pid=c.pid)
 for _ in range(80):
  if c.poll() is not None: trace('child_already_exit',rc=c.returncode); break
  cpu=psutil.Process(c.pid).cpu_times(); trace('cpu',user=cpu.user,system=cpu.system)
  if cpu.user+cpu.system>.3: break
  time.sleep(.025)
 trace('prekill',output_exists=(r/'output.json').exists())
 p.kill(); trace('signal_sent'); p.wait(timeout=5); trace('parent_reaped',pid_exists=psutil.pid_exists(p.pid))
 out,err=c.communicate(timeout=5); trace('child_exit',rc=c.returncode,out=out,err=err,
    output_exists=(r/'output.json').exists())
finally:
 for proc in (c,p):
  if proc.poll() is None: proc.kill()
  proc.wait(timeout=5)
a.original.atomic(r/'TRACE.json',rows)
print(json.dumps(rows))
