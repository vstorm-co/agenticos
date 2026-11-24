# Babysit PR

Watch a pull request through CI and review bots, reporting only what
changed, and stop when the bots are green on the latest commit. This
is Theo's tstack `babysit-pr` skill as a capability: the procedure
lives in the `babysit-pr` skill
(`backend/app/core/catalog/skills/babysit-pr/SKILL.md`), which says
when to watch; this page says what the capability does with a
snapshot.

## How a watch works

The agent watches with the monitor capability — `start_monitor` on
`gh pr checks --watch` — and hands each new snapshot to
`babysit_pr_check` with the repo, PR number, head SHA, and the checks
as reported. The tool classifies the snapshot: only the current
commit's checks count, each failed check is named real or flake with
its reason, and only the checks that changed since the last snapshot
are reported. When nothing changed and the watch continues, the
report is empty, and the agent ends its turn without a message —
never posting or saying "still waiting".

The watch ends when the tool says green on the latest commit, when
the watch runs past its configured maximum without green, or when
the agent stops it with `babysit_pr_stop` — ready, blocked, or
asking the user a question. A merge or close ends the watch on its
own.

## What it deliberately does not do

- **Merge, comment, or take any other action on the PR.** Watching
  and reporting only. A wake is news, not a merge decision; the
  merge gate is checked by the agent, and merging needs the user's
  explicit request.
- **Run `gh` itself.** Reading the checks is the agent's job, under
  the monitor capability. This capability classifies snapshots it is
  handed, so it needs no GitHub credential and no sandbox scope.
- **Poll in a tight loop.** Polls are at least 60 seconds apart
  (five minutes by default), and when the GitHub rate limit is
  nearly used up the agent asks `babysit_pr_rate_limit` first and
  waits for the reset instead of watching again.
- **Watch a PR it does not own.** One watcher per PR, and only the
  thread that owns the PR watches it. A delegated child never
  watches; starting a second PR while one is active is refused.
- **Keep watch events anywhere but the manifest.** Events live in
  the run manifest's JSONB, beside the requests. There is no table
  to migrate and no event to query across runs.

A flake classification is a heuristic over the check's own failure
text, not a verdict: the agent verifies every finding against the
source before dismissing it with a written reason, and a failure
whose text matches no infrastructure signal is real until proven
otherwise.
