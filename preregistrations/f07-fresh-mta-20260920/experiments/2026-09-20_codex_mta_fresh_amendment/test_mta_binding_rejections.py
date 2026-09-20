"""Negative binding controls, entirely synthetic and endpoint-free.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
"""
from unittest.mock import patch
from pathlib import Path
from datetime import datetime,timezone
import copy,json,hashlib
import mta_supervisor as a
root=a.HERE/'MTA_NEGATIVE_BINDING';root.mkdir(exist_ok=False)
candidate=json.loads((a.HERE/'MTA_PROTOCOL_CANDIDATE_V1.json').read_bytes())
sources=candidate['runtime_source_sha256']
frozen={'schema_version':3,'run_id':a.RUN,'lineage':{key:{'path':key,'sha256':key,'size_bytes':1}
 for key in ('candidate','review','decision','final')}}
review={'binds_candidate_sha256':'candidate'}
decision={'binds_candidate_sha256':'candidate','binds_review_sha256':'review',
 'status':'ACCEPT_FOR_PROSPECTIVE_FREEZE','unresolved_blockers':[]}
final={'binds_candidate_sha256':'candidate','binds_decision_sha256':'decision',
 'runtime_source_sha256':sources,'runtime':candidate['runtime']}
receipt={'status':'CENTRAL_PRELAUNCH_PASS','freeze_contract_sha256':'contract',
 'candidate_sha256':'candidate','exit_code':0,'stdout':'PASS experiment freeze PRELAUNCH: synthetic'}
docs={'contract':frozen,'candidate':candidate,'review':review,'decision':decision,'final':final,'receipt':receipt}
config={'status':'FINAL_REVIEWED_PUBLIC_MTA_AMENDMENT','seeds':list(range(1000,1040)),
 'freeze_contract':{'path':'contract','sha256':'contract','size_bytes':1},'source_sha256':sources,
 'runtime':candidate['runtime'],'central_prelaunch_receipt':{'path':'receipt','sha256':'receipt','size_bytes':1}}
cases=[('wrong_seed_set',lambda c,d:c['seeds'].pop()),
 ('wrong_freeze_identity',lambda c,d:d['contract'].update(run_id='wrong')),
 ('broken_review_lineage',lambda c,d:d['review'].update(binds_candidate_sha256='wrong')),
 ('unresolved_blocker',lambda c,d:d['decision'].update(unresolved_blockers=['blocked'])),
 ('missing_adapter_source',lambda c,d:c['source_sha256'].pop(a.SELF)),
 ('runtime_drift',lambda c,d:d['candidate']['runtime'].update(python='0.0.0')),
 ('central_validation_failed',lambda c,d:d['receipt'].update(exit_code=1)),
 ('wrong_contract_receipt',lambda c,d:d['receipt'].update(freeze_contract_sha256='wrong'))]
rows=[]
for name,change in cases:
 c,d=copy.deepcopy(config),copy.deepcopy(docs)
 change(c,d)
 p=root/(name+'.json');p.write_text(json.dumps(c),encoding='utf-8')
 with patch.object(a,'read_ref',side_effect=lambda ref:d[ref['path']]), \
      patch.object(a,'remote_json',side_effect=AssertionError('Network must not be reached')), \
      patch.object(a.subprocess,'run',side_effect=AssertionError('Runtime/model process must not be reached')):
  try:a.launch_binding(p)
  except ValueError as e:rows.append({'case':name,'rejected':True,'reason':str(e)})
  else:raise AssertionError('Accepted invalid binding: '+name)
report={'at':datetime.now(timezone.utc).isoformat(),'tool':'Codex','model':'gpt-6-astra / xhigh',
 'operation_id':'f07-mta-fresh-to-round-f-20260920','status':'PASS_SYNTHETIC_MTA_BINDING_REJECTIONS',
 'scope':'read_ref is injected with synthetic lineage; actual public positive path remains untested before publication',
 'scientific_compute':False,'checks':rows,'sources':{p:hashlib.sha256((a.PROJECT/p).read_bytes()).hexdigest() for p in sorted(a.EXTRA)}}
(root/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':report['status'],'checks':len(rows)}))
