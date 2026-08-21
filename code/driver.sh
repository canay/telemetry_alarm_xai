#!/bin/bash
# Resumable driver: runs pending work units two at a time until MAX_SEC.
cd "$(dirname "$0")"
MAX_SEC=${MAX_SEC:-30}
START=$(date +%s)
UNITS=()
for s in 0 1 2 3 4; do UNITS+=("feat:$s"); done
for s in 0 1 2 3 4; do for m in lr dtree iforest hgb pca ae; do UNITS+=("model:$s:$m"); done; done
for s in 0 1 2 3 4; do UNITS+=("cross:$s"); done
PENDING=()
for u in "${UNITS[@]}"; do
  IFS=: read -r a b c <<< "$u"
  case $a in
    feat) f="../ckpt/feat_seed$b.npz";;
    model) f="../ckpt/model_seed${b}_$c.json";;
    cross) f="../ckpt/cross_seed$b.json";;
  esac
  [ -f "$f" ] || PENDING+=("$u")
done
echo "pending: ${#PENDING[@]}"
i=0
while [ $i -lt ${#PENDING[@]} ]; do
  now=$(date +%s)
  if [ $((now-START)) -ge $MAX_SEC ]; then echo "BUDGET ($((${#PENDING[@]}-i)) left)"; exit 0; fi
  u1=${PENDING[$i]}; u2=""
  [ $((i+1)) -lt ${#PENDING[@]} ] && u2=${PENDING[$((i+1))]}
  PYTHONPYCACHEPREFIX=/tmp/pyc OMP_NUM_THREADS=1 python3 run_unit.py "$u1" 2>>../results/driver_err.log &
  P1=$!
  if [ -n "$u2" ]; then
    PYTHONPYCACHEPREFIX=/tmp/pyc OMP_NUM_THREADS=1 python3 run_unit.py "$u2" 2>>../results/driver_err.log &
    P2=$!
    wait $P2 || echo "FAIL $u2"
  fi
  wait $P1 || echo "FAIL $u1"
  i=$((i+2))
done
echo ALLDONE
