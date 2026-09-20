"""Exercise the actual MTA wrapper and Linux child enumeration.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
"""
import sys, subprocess, threading, json, time
from pathlib import Path
import psutil
import mta_supervisor as adapter
adapter.configure()
root=adapter.HERE/'MTA_GUARD_CHECKS'
root.mkdir(exist_ok=False)
children=[]
def launch_from_thread():
    children.append(subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']))
t=threading.Thread(target=launch_from_thread); t.start();t.join()
try:
    direct=psutil.Process().children()
    recursive=psutil.Process().children(recursive=True)
    assert {p.pid for p in direct}=={children[0].pid}
    assert {p.pid for p in recursive}=={children[0].pid}
finally:
    for p in children: p.kill();p.wait(timeout=5)
assert psutil.Process().children(recursive=True)==[]
class TestSubprocessAdapter(adapter.SubprocessAdapter):
    def Popen(self,command,*args,**kwargs):
        command=list(command)
        if len(command)>1 and Path(command[1]).resolve()==adapter.BASE/'fresh_supervisor.py':
            command[1]=str(adapter.HERE/'mta_supervisor.py')
        return super().Popen(command,*args,**kwargs)
    def run(self,command,*args,**kwargs):
        command=list(command)
        if len(command)>1 and Path(command[1]).resolve()==adapter.BASE/'fresh_supervisor.py':
            command[1]=str(adapter.HERE/'mta_supervisor.py')
        return subprocess.run(command,*args,**kwargs)
import test_runtime_guards as guards
guards.subprocess=TestSubprocessAdapter()
sys.argv=['test_runtime_guards.py','--output','mta_guards_v3_20260920']
assert guards.main()==0
import test_supervisor_lifecycle as lifecycle
lifecycle.SUPERVISOR=adapter.HERE/'mta_supervisor.py'
sys.argv=['test_supervisor_lifecycle.py','--prefix','mta_lifecycle_v3_20260920']
lifecycle.main()
adapter.original.atomic(root/'REPORT.json',{'status':'PASS_MTA_SUBTREE_AND_WRAPPER_GUARDS',
    'thread_spawned_child_detected':True,'unrelated_processes_returned':False,
    'scientific_compute':False,'at':adapter.original.now(),
    'sources':{p:adapter.original.sha(adapter.PROJECT/p) for p in sorted(adapter.EXTRA)}})
print('PASS_MTA_GUARD_CHECKS')
