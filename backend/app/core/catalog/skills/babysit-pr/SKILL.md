---
name: babysit-pr
description: Monitor a pull request through review and CI. Use when the user asks to monitor, watch, or babysit a PR.
category: engineering
---

# Babysit PR

Many repos have AI review bots. They're helpful, even if they are not always
right. Babysitting is watching, not merging: the watcher reports what
changed and stops when the bots are green on the latest commit. It never
merges, comments, or takes any other action on the PR by itself.

## Waiting

Never write your own watcher, polling loop, or `sleep` loop. Use one watcher
per PR: the `babysit_pr` capability's tools in T3OS, `watch_pull_request`
in T3 Code, `pr-wait` everywhere else. Never run two watchers on the same
PR. Every watcher on a GitHub account shares one rate limit.

### In T3OS: the babysit-pr capability

Handle the existing checks and comments first. Then watch with the
monitor capability: `start_monitor` on `gh pr checks --watch` for the PR
(or `gh pr checks` re-run at the capability's poll interval when the
watch command is unavailable). Each new snapshot goes to
`babysit_pr_check` with the repo, PR number, head SHA, and the checks
as reported. The tool classifies the snapshot, reports only what
changed, and says what to do next. When it says green, report the PR
ready and call `babysit_pr_stop`.

- **Only the thread that owns the PR watches it.** If you are a delegated
  child task (a reviewer, a Sol round, any delegate child), never call
  the babysit tools. The parent owns the PR. Do not watch PRs you are
  not working on.
- **A wake is news, not a merge decision.** Check the merge gate yourself.
- **Unwatch when you hand off.** A watched thread stays in Working and out
  of the user's inbox. When you stop (ready, blocked, or asking the user
  a question), call `babysit_pr_stop` first. A merge or close ends the
  watch on its own.
- **"Stopped watching, could not read it"** usually means GitHub's rate
  limit is used up. Run `gh api rate_limit --jq .resources.graphql`
  before you watch again, and pass what it says to
  `babysit_pr_rate_limit`. If `remaining` is near 0, wait for `reset`,
  then watch again. Never watch again in a tight loop: polls are at
  least 60 seconds apart, five minutes by default.
- When an event needs no action, end your turn without a message.
  Never post or say "still waiting". The tool returns an empty report
  when nothing changed — that is the instruction to stay quiet.

### In T3 Code: `watch_pull_request`

Handle the existing checks and comments first. Then call
`watch_pull_request` and end your turn. T3 Code wakes you with a message when
a check fails, the required checks pass, someone comments or reviews, or the
branch conflicts. The same ownership, unwatch, rate-limit, and
never-"still waiting" rules apply.

### Everywhere else: `pr-wait`

Wait with `scripts/pr-wait` from the tstack skill's directory (use its
absolute path).

```bash
pr-wait <pr> [--repo owner/name] [--until ready|green|any-change]
```

It prints one line per real event. It exits 0 when the `--until` condition is
met or the PR merges, 1 when it needs you (a required check failed, conflicts,
unresolved threads, PR closed), and 2 on bad input.

- `ready` (default): required checks green, Greptile or Macroscope reviewed the
  head, and no unresolved threads. Use this to babysit.
- `green`: required checks only. Use it when the repo has no Greptile or
  Macroscope.
- `any-change`: exit on the first event.

Start it again after you push, after you handle an exit 1, and after a resume.
It remembers what it already reported, so nothing that arrived in between is
lost. If it says another pid already watches the PR, do not start a second one.
Kill the old one only if its events do not reach you.

## GitHub rate limits

`gh pr create`, `gh pr view`, and `gh pr checks` use GraphQL. When GraphQL is
used up, the REST limit is separate and usually still has room. Use
`gh api repos/<owner>/<repo>/pulls/<n>` to read a PR, and
`gh api repos/<owner>/<repo>/commits/<sha>/check-runs` for checks.

## Reviews

Only act on checks and comments newer than the latest push. Verify every bot
finding against the source before changing code. Fix real findings and CI
failures, distinguish repository failures from infrastructure flakes, and reply
with a written reason when dismissing false positives. The
`babysit_pr_check` result names each failed check real or flake with its
reason — a flake is a heuristic over the failure text, not a verdict, so
read the failure yourself before dismissing it.

If the repo has `.macroscope/check-run-agents/*.md`, read those rules before you
reply to a Macroscope finding. Its findings cite them.

CodeRabbit is advisory. Treat its findings like any other finding, but never
wait for it and never hold a merge for it.

If a review bot leaves feedback you believe is not worth addressing, reply with
a written reason and resolve the comment. Use the `leaving-pr-comments` skill
for every comment posted on the user's behalf.

Screenshots and videos help as well, when you have a way to upload them.

Keep the PR at the size the user's goal needs. Review loops tend to grow a
PR one cheap-looking fix at a time. Fix real bugs in the intended case.
Decline the rest with a written reason, and list them as follow-ups:
unneeded tests, guards for edge cases that do not matter, extra integration
or compatibility, and small performance costs. Prefer the fix that deletes or
narrows code.

## Base branch and merging

Keep an eye on changes to `main` and rebase when needed. A new head SHA in
a `babysit_pr_check` snapshot reports the head moved: the checks above are
for the new head, so wait for green on this commit, not the last one.
If an overlapping PR makes this one obsolete, stop monitoring, report it to
the user, and ask before closing the PR unless closure was explicitly authorized.

If nothing has changed, stay quiet rather than posting filler comments. Stop
when the watch says green on the latest head. Merge only when the user
explicitly requested it; otherwise report that the PR is ready. Right before
a merge, run `git fetch` and check the PR again. Never merge when it is BEHIND
or DIRTY, or when base commits that landed after the last green run touch this
PR's files. Rebase, push, and wait for green again.
