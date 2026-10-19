#!/usr/bin/env bash
# DBOS: a worker that dies mid-job and comes back as a NEW container (new hostname,
# so a new executor ID), as on a deploy. Does its in-flight workflow ever run again?
set -euo pipefail
cd /Users/kacperwlodarczyk/PycharmProjects/agenticos/experiments/task-queues
export BENCH_RUN_LABEL=dbos-recreate
dc() { docker compose --profile dbos "$@"; }
dc down -v --remove-orphans >/dev/null 2>&1 || true
dc up -d --wait postgres redis >/dev/null
docker compose --profile driver run --rm -T driver python -m bench.driver --backend dbos --variant dbos --scenario setup --label dbos-recreate-setup >/dev/null 2>&1
dc up -d w-dbos >/dev/null
sleep 20
docker compose --profile driver run --rm -T driver python -c "
import asyncio
from bench import workload
from bench.backends import dbos_app
async def main():
    for i in range(3):
        await dbos_app.submit(workload.new_job('dbos-recreate', 'agent', 'org-0', extra={'wait': 45}))
asyncio.run(main())
" 2>/dev/null
sleep 8
echo "before kill:"; dc exec -T postgres psql -U bench -At -c "select status, executor_id, count(*) from dbos.workflow_status where name='bench.run' group by 1,2"
docker kill "$(dc ps -q w-dbos)" >/dev/null
dc up -d --force-recreate w-dbos >/dev/null
sleep 120
echo "120 s after recreate:"; dc exec -T postgres psql -U bench -At -c "select status, executor_id, count(*) from dbos.workflow_status where name='bench.run' group by 1,2"
echo "live executor: $(dc exec -T w-dbos hostname)"
dc down -v --remove-orphans >/dev/null 2>&1 || true
