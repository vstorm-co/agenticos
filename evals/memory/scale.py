"""Measure live ledger reads with optional concurrent writers in isolated synthetic tenants."""

import argparse
import asyncio
import json
import os
import random
import sys
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid5

from report import percentile
from run import git_sha
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.memory_claim import ClaimScope
from app.services.memory import claims


async def measure(args: argparse.Namespace) -> dict[str, object]:
    from ledger import LOGICAL_CLOCK, disposable_engine, insert_rows, isolated_scope

    engine = disposable_engine(os.environ.get("MEMORY_BENCH_AGENTICOS_DSN", ""))
    mixed = args.readers > 1 or args.writes > 0 or args.tenants > 1
    try:
        async with AsyncExitStack() as stack:
            scopes = [
                await stack.enter_async_context(isolated_scope(engine, committed=mixed))
                for _ in range(args.tenants)
            ]
            rng = random.Random(args.seed)  # noqa: S311 - Reproducible synthetic workload.
            requested = min(args.rows, args.targets)
            load_order = rng.sample(range(args.rows), k=requested)
            target_by_index = {row: target for target, row in enumerate(load_order)}
            valid_at = LOGICAL_CLOCK + timedelta(seconds=args.rows)
            revisions = sorted(
                (
                    await scopes[0][0].execute(text("SELECT version_num FROM alembic_version"))
                ).scalars()
            )
            started = perf_counter()
            for tenant_index, (db, organization_id, scope) in enumerate(scopes):
                rows = args.rows if tenant_index == 0 else args.small_tenant_rows
                rows = max(rows, requested)
                # Use the same object words and markers in each tenant. A wrong-tenant
                # hit would still match the query but carries the wrong source ID.
                positions = load_order if tenant_index == 0 else list(range(requested))
                markers = target_by_index if tenant_index == 0 else dict(enumerate(positions))
                await insert_rows(
                    db,
                    organization_id,
                    scope,
                    (
                        (
                            uuid5(organization_id, f"synthetic-{index}"),
                            f"atlas case marker-{markers[index]:06} target 40 employees"
                            if index in markers
                            else "atlas case archived marker-zzzzzz department noise",
                            LOGICAL_CLOCK + timedelta(seconds=index),
                        )
                        for index in range(rows)
                    ),
                )
                if mixed:
                    await db.commit()
            load_ms = (perf_counter() - started) * 1_000

            async def read(
                db: AsyncSession, org: UUID, scope: ClaimScope, tenant: int, target: int
            ) -> tuple[float, bool]:
                before = perf_counter()
                hits = await claims.recall(
                    db,
                    organization_id=org,
                    scopes=[scope],
                    query=f"atlas case marker-{target:06}",
                    as_of=valid_at,
                    limit=args.top_k,
                )
                expected = load_order[target] if tenant == 0 else target
                return (perf_counter() - before) * 1_000, bool(
                    hits and hits[0].source_conversation_id == uuid5(org, f"synthetic-{expected}")
                )

            for index in range(args.warmup):
                tenant = index % len(scopes)
                db, org, scope = scopes[tenant]
                await read(db, org, scope, tenant, rng.randrange(requested))
                if mixed:
                    await db.rollback()

            targets = [
                (index % len(scopes), rng.randrange(requested)) for index in range(args.repetitions)
            ]

            async def read_lane(lane: int) -> list[tuple[float, bool]]:
                result = []
                for tenant, target in targets[lane :: args.readers]:
                    db, org, scope = scopes[tenant]
                    if mixed:
                        async with AsyncSession(engine) as reader:
                            result.append(await read(reader, org, scope, tenant, target))
                    else:
                        result.append(await read(db, org, scope, tenant, target))
                return result

            async def write_lane() -> list[float]:
                samples = []
                async with AsyncSession(engine) as writer:
                    for sequence in range(args.writes):
                        _, org, scope = scopes[sequence % len(scopes)]
                        before = perf_counter()
                        await claims.remember(
                            writer,
                            organization_id=org,
                            scope=scope,
                            subject=f"concurrent_{sequence}",
                            statement=f"Concurrent observation number {sequence}",
                        )
                        await writer.commit()
                        samples.append((perf_counter() - before) * 1_000)
                return samples

            async with asyncio.TaskGroup() as group:
                readers = [group.create_task(read_lane(lane)) for lane in range(args.readers)]
                writer = group.create_task(write_lane())
            observations = [elapsed for reader in readers for elapsed, _ in reader.result()]
            write_samples = writer.result()
            missed = sum(not matched for reader in readers for _, matched in reader.result())
            return {
                "mode": "mixed_ledger" if mixed else "sequential_warm_ledger",
                "git_sha": git_sha(),
                "alembic_revisions": revisions,
                "rows": args.rows,
                "tenants": args.tenants,
                "small_tenant_rows": max(args.small_tenant_rows, requested)
                if args.tenants > 1
                else 0,
                "readers": args.readers,
                "read_limit": args.top_k,
                "seed": args.seed,
                "targets": requested,
                "load_ms": load_ms,
                "warmup": args.warmup,
                "samples_ms": observations,
                "write_samples_ms": write_samples,
                "recall_ms_p50": percentile(observations, 0.5),
                "recall_ms_p95": percentile(observations, 0.95),
                "recall_ms_p99": percentile(observations, 0.99),
                "write_ms_p95": percentile(write_samples, 0.95),
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
    parser.add_argument("--readers", type=int, default=1)
    parser.add_argument("--writes", type=int, default=0)
    parser.add_argument("--tenants", type=int, default=1)
    parser.add_argument("--small-tenant-rows", type=int, default=1000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (
        not 1 <= args.rows <= 10_000_000
        or not 1 <= args.top_k <= 100
        or min(args.targets, args.repetitions) < 1
        or args.warmup < 0
        or not 1 <= args.readers <= 16
        or args.writes < 0
        or not 1 <= args.tenants <= 10
        or not 1 <= args.small_tenant_rows <= 1_000_000
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
