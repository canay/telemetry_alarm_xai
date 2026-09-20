"""Recompute the preregistered summaries from released policy endpoints, without refitting.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
This public consumer is separate from the frozen scientific producer.
"""
from pathlib import Path
import argparse, hashlib, json, math, sys
RUN_ID='2026-09-20_codex_mta_fresh_internal_replication_v1'
TOLERANCE={'absolute':2e-12,'relative':2e-11}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):
    return json.loads(p.read_bytes(),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))

def compare(a,b,path='root'):
    if isinstance(a,dict) and isinstance(b,dict):
        if set(a)!=set(b):raise ValueError('Key mismatch: '+path)
        for key in a:compare(a[key],b[key],path+'.'+key)
    elif isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):raise ValueError('Length mismatch: '+path)
        for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+f'[{i}]')
    elif type(a) is int:
        if type(b) is not int or a!=b:raise ValueError('Integer mismatch: '+path)
    elif type(a) is float:
        if type(b) is not float or not math.isclose(a,b,abs_tol=TOLERANCE['absolute'],rel_tol=TOLERANCE['relative']):raise ValueError('Numeric mismatch: '+path)
    elif type(a)!=type(b) or a!=b:raise ValueError('Value mismatch: '+path)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True,help='Extract all four assets to one directory; pass its run/ subdirectory')
    parser.add_argument('--package-dir',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--output',type=Path,help='Optional new JSON output; existing files are never overwritten')
    args=parser.parse_args(); package=args.package_dir.resolve()
    code=package/'code_snapshot/experiments/2026-09-19_codex_local_fresh_preflight/seed_level_reducer.py'
    expected='985f0b4d275f7c18dcac56ff65aa4feb9552c0a6a3dd459ffffddd935f0dd358'
    if sha(code)!=expected:raise ValueError('Frozen reducer hash mismatch')
    manifest_path=package/'PUBLIC_RESULTS_MANIFEST.json'; manifest=load(manifest_path)
    if manifest['run_id']!=RUN_ID or manifest['terminal_status']!='completed' or manifest['independent_seed_count']!=40 or manifest['policy_cells']!=51840:raise ValueError('Public run identity mismatch')
    indexed={r['path']:r for r in manifest['scientific_members']}
    if len(indexed)!=len(manifest['scientific_members']) or len(indexed)!=5320:raise ValueError('Public member inventory mismatch')
    aggregate_path=package/'aggregate.json'
    if sha(aggregate_path)!=manifest['aggregate_sha256']:raise ValueError('Released aggregate digest mismatch')
    sys.path.insert(0,str(code.parent))
    from seed_level_reducer import reduce_rows
    rows=[];inputs=[]
    for seed in range(1000,1040):
        relative=f'policy/seed{seed}/results.json';p=args.run_dir/relative;r=indexed[relative]
        if r['member']!='run/'+relative or sha(p)!=r['sha256'] or p.stat().st_size!=r['size_bytes']:raise ValueError('Released endpoint digest/size mismatch')
        doc=load(p)
        if type(doc['seed']) is not int or doc['seed']!=seed or len(doc['rows'])!=1296:raise ValueError('Seed identity/cardinality mismatch')
        inputs.append({'path':relative,'sha256':r['sha256'],'size_bytes':r['size_bytes']})
        rows.extend(doc['rows'])
    result=reduce_rows(rows)
    compare(result,load(aggregate_path))
    receipt={'status':'PUBLIC_STORED_ENDPOINTS_VERIFIED_AND_SUMMARY_MATCHED_WITHIN_TOLERANCE',
             'run_id':RUN_ID,'rows':len(rows),'seed_count':len(result['seed_ids']),
             'family_verdict':result['family_verdict'],'tolerance':TOLERANCE,
             'manifest_sha256':sha(manifest_path),'reducer_sha256':sha(code),
             'aggregate_sha256':sha(aggregate_path),'verified_inputs':inputs,
             'scope':'40 released endpoint files only; not a full raw-data rerun or byte-exact aggregate reproduction',
             'model_fits':0,'policy_evaluations':0}
    if args.output:
        with args.output.open('x',encoding='utf-8') as f:json.dump({'verification':receipt,'recomputed_summary':result},f,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='verified_inputs'}))

if __name__=='__main__':main()
