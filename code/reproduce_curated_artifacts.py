"""Rebuild curated summaries and Figures 5/S1 from saved outputs only."""
from pathlib import Path
import argparse,json,subprocess,sys
import numpy as np
import pandas as pd
from build_criticality_manuscript_artifacts import build_figure
from round_b_derived_evidence import signature_pair_audit,validate_signature_input
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args();root=Path(__file__).resolve().parents[1]
out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
subprocess.run([sys.executable,str(root/'code/aggregate.py'),'--checkpoint-dir',str(root/'results/raw'),'--output',str(out/'results_summary.json'),'--versions-output',str(out/'aggregation_versions.txt')],check=True)
def compare(a,b,path=''):
 if isinstance(a,dict):
  assert a.keys()==b.keys(),path
  for key in a:compare(a[key],b[key],path+'/'+key)
 elif isinstance(a,list):
  assert len(a)==len(b),path
  for i,(u,v) in enumerate(zip(a,b)):compare(u,v,path+'/'+str(i))
 elif isinstance(a,(float,int)) and not isinstance(a,bool):
  assert np.isclose(a,b,rtol=1e-10,atol=1e-12,equal_nan=True),(path,a,b)
 else:assert a==b,(path,a,b)
compare(json.loads((root/'results/results_summary.json').read_bytes()),json.loads((out/'results_summary.json').read_bytes()))
pair_frames=[];summaries=[]
for dataset,relative in [('opssat_ad','results/opssat_transfer_benchmark/feature_signature_audit.csv'),('kddcup99','results/second_transfer_benchmark_audit_rerun/feature_signature_audit.csv')]:
 p=root/relative;frame=pd.read_csv(p);validate_signature_input(frame,p)
 pairs,summary=signature_pair_audit(dataset,frame);pair_frames.append(pairs);summaries.append(summary)
pairs=pd.concat(pair_frames,ignore_index=True);summary=pd.concat(summaries,ignore_index=True)
for name,frame in [('signature_pair_audit.csv',pairs),('signature_pair_summary.csv',summary)]:
 expected=pd.read_csv(root/'results/signature_pair_audit'/name)
 if 'degenerate_reason' in expected:
  expected['degenerate_reason']=expected['degenerate_reason'].fillna('')
 keys=['dataset','model']+(['seed_a','seed_b'] if name=='signature_pair_audit.csv' else [])
 pd.testing.assert_frame_equal(frame.sort_values(keys).reset_index(drop=True),expected.sort_values(keys).reset_index(drop=True),check_dtype=False,check_exact=False,rtol=1e-10,atol=1e-12)
 frame.to_csv(out/name,index=False)
op=summary[summary.dataset=='opssat_ad'];assert len(op)==4 and (op.n_pairs_valid==10).all() and (op.n_pairs_degenerate==0).all()
build_figure(pd.read_csv(root/'results/scenario_utility_v1_2/figure_inputs/cell_decisions.csv'),out/'fig_prioritization')
subprocess.run([sys.executable,str(root/'code/plot_round_b_kdd_signature_pairs.py'),'--pair-audit',str(out/'signature_pair_audit.csv'),'--out-dir',str(out)],check=True)
print('CURATED_ARTIFACTS_VERIFIED: saved-output summary, signature validity, Figure 5, Figure S1; zero model fits')
