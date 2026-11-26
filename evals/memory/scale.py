"""Measure the live ledger query on synthetic claims in a rollback-only transaction."""

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid5

from report import percentile
from run import git_sha


async def measure(args: argparse.Namespace) -> dict[str, object]:
    from ledger import LOGICAL_CLOCK, disposable_engine, insert_rows, isolated_scope, recall
    from sqlalchemy import text

    engine = disposable_engine(os.environ.get("MEMORY_BENCH_AGENTICOS_DSN", ""))
    try:
        async with isolated_scope(engine) as (db, organization_id, scope):
            revision = sorted(
                (await db.execute(text("SELECT version_num FROM alembic_version"))).scalars()
            )
            rng = random.Random(args.seed)  # noqa: S311 - Reproducible synthetic workload.
            requested = min(args.rows, args.targets)
            load_order = rng.sample(range(args.rows), k=requested)
            target_by_index = {row: target for target, row in enumerate(load_order)}
            rows = (
                (
                    uuid5(organization_id, f"synthetic-{index}"),
                    f"atlas case marker-{target_by_index[index]:06} target 40 employees"
                    if index in target_by_index
                    else "atlas case archived marker-zzzzzz department noise",
                    LOGICAL_CLOCK + timedelta(seconds=index),
                )
                for index in range(args.rows)
            )
            started = perf_counter()
            await insert_rows(db, organization_id, scope, rows)
            load_ms = (perf_counter() - started) * 1_000
            observations = []
            missed = 0
            for index in range(args.warmup + args.repetitions):
                target = rng.randrange(requested)
                started = perf_counter()
                hits = await recall(
                    db,
                    organization_id=organization_id,
                    scopes=[scope],
                    query=f"atlas case marker-{target:06}",
                    as_of=LOGICAL_CLOCK + timedelta(seconds=args.rows),
                    limit=args.top_k,
                )
                elapsed = (perf_counter() - started) * 1_000
                if index >= args.warmup:
                    observations.append(elapsed)
                    missed += int(
                        not hits
                        or hits[0].source_conversation_id
                        != uuid5(organization_id, f"synthetic-{load_order[target]}")
                    )
            return {
                "mode": "sequential_warm_ledger",
                "git_sha": git_sha(),
                "alembic_revisions": revision,
                "rows": args.rows,
                "read_limit": args.top_k,
                "seed": args.seed,
                "targets": requested,
                "load_ms": load_ms,
                "warmup": args.warmup,
                "samples_ms": observations,
                "recall_ms_p50": percentile(observations, 0.5),
                "recall_ms_p95": percentile(observations, 0.95),
                "top1_misses": missed,
            }
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--targets", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (
        not 1 <= args.rows <= 10_000_000
        or not 1 <= args.top_k <= 100
        or min(args.targets, args.repetitions) < 1
        or args.warmup < 0
    ):
        parser.error("Use 1-10M rows, 1-100 results and positive targets/repetitions.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        parser.error("Use a new output path.")
    result = asyncio.run(measure(args))
    with args.out.open("x", encoding="utf-8") as stream:
        print(json.dumps(result, indent=2), file=stream)
    print(f"Result written to {args.out}", file=sys.stderr)
    return int(bool(result["top1_misses"]))


if __name__ == "__main__":
    raise SystemExit(main())
