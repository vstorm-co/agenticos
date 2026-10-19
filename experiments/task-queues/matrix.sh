#!/usr/bin/env bash
# The full comparison: every variant through every scenario it takes part in.
# Prefect last - its runs take longest. Fairness variants only differ under the
# tenant flood, so they run that scenario alone.
cd "$(dirname "$0")"
ALL=(pgqueue celery-prefork celery-threads taskiq dramatiq saq procrastinate hatchet prefect-tasks prefect-serve prefect-serve-20 prefect-serve-pg)
run() {
  start=$(date +%s)
  if ./run.sh "$1" "$2" >"results/.$1-$2.out" 2>&1; then status=OK; else status=FAIL; fi
  echo "$(date +%H:%M) $1 $2 $status $(( $(date +%s) - start ))s"
}
for scenario in workflow mix tenants; do
  for variant in "${ALL[@]}"; do run "$variant" "$scenario"; done
done
run pgqueue-fair tenants
run hatchet-fair tenants
echo DONE
