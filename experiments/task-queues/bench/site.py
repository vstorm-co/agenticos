"""Build the report page from `results/`, with the numbers the tables use.

    python -m bench.site results report/template.html > report/index.html

The page is one self-contained file: the summaries `bench.report` computes, plus
the per-job series the figures draw, are written into it as JSON. Nothing is
fetched when it is opened.
"""

import glob
import json
import os
import sys
from collections import defaultdict
from typing import Any

from bench.report import load_jobs, summarize

PLACEHOLDER = "/*__BENCH_DATA__*/null"


def _tenant_series(json_path: str, started_at: float) -> dict[str, Any]:
    """The small organization's waits, and completions per second, over the run."""
    jobs = load_jobs(json_path.replace(".json", ".events.csv"))
    small = sorted(
        (round(j["enq"] - started_at, 2), round(min(j["starts"]) - j["enq"], 3))
        for j in jobs.values()
        if j["tenant"] == "org-small" and j["starts"]
    )
    per_second: dict[int, int] = defaultdict(int)
    for j in jobs.values():
        if j["kind"] != "sweep" and j["finishes"]:
            per_second[int(min(j["finishes"]) - started_at)] += 1
    horizon = max(per_second, default=0)
    return {
        "small": small,
        "done_per_s": [per_second.get(second, 0) for second in range(horizon + 1)],
    }


def build(directory: str) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    series: dict[str, Any] = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        if path.endswith("summary.json"):
            continue
        summary = summarize(path)
        summaries.append(summary)
        if summary["scenario"] == "tenants":
            result = json.load(open(path))
            series[summary["variant"]] = _tenant_series(path, result["started_at"])
    return {"summaries": summaries, "tenant_series": series}


def main(directory: str, template: str) -> None:
    page = open(template).read()
    if PLACEHOLDER not in page:
        raise SystemExit(f"{template} has no {PLACEHOLDER} to fill")
    data = json.dumps(build(directory), separators=(",", ":"), default=float)
    sys.stdout.write(page.replace(PLACEHOLDER, data))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results", sys.argv[2] if len(sys.argv) > 2 else "report/template.html")
