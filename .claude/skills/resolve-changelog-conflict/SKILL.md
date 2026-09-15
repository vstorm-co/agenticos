---
name: resolve-changelog-conflict
description: Resolve a merge conflict in CHANGELOG.md by detecting the file's own convention (Keep a Changelog per-version sections, monthly sections, a single [Unreleased] bucket, or another format) and folding the other side's entries into it. Use whenever git reports a conflict in CHANGELOG.md, or when entries in an older format need folding into the current one.
---

# Resolve a CHANGELOG.md conflict

Conflicts happen when two branches append near the same lines, or when one branch still
carries an older changelog convention than the other. The resolution is never "pick a side
wholesale": determine which side reflects this repo's *current, documented* convention, keep
its structure, then re-express the other side's *new* entries inside it.

**Do not assume a specific format** (monthly sections, per-version sections, ticket-prefix
style). Detect it from the file itself — every repo's changelog is different, and guessing
wrong produces a "fix" that contradicts the project's own header and recent history.

## Steps

1. **Learn this repo's actual convention before touching anything.**
   - Read the file's own header/preamble — many state their format explicitly (e.g. "The
     format follows [Keep a Changelog]").
   - Look at the most recent non-conflicted entries (`git log -p -- CHANGELOG.md` on
     `main`/the target branch) to see the real grouping (per-version `## [x.y.z] - date`,
     monthly `## YYYY-MM`, a flat `## [Unreleased]`), the category headers used (`###
     Added`/`Changed`/`Fixed`/`Removed`/`Security`, or something else), and how entries cite
     their origin (a PR number like `(#123)`, a ticket prefix like `(PROJ-123)`, a commit
     hash, a date, or a mix). Mirror what you find — do not invent a ticket prefix or
     category set the repo doesn't already use.
   - If the repo has a rule file or doc describing the changelog (check `CLAUDE.md`,
     `CONTRIBUTING.md`, or a comment in the file header), follow it as the source of truth
     over inference from history.

2. **Identify what the other side actually adds.** `<incoming>` is a branch only during a
   merge. A rebase or a cherry-pick is replaying one commit, so the incoming side is that
   commit rather than a branch, and the placeholders below resolve differently:

   | Operation | `<incoming>` | `<merge-base>` |
   |---|---|---|
   | merge | the branch being merged | `git merge-base HEAD MERGE_HEAD` |
   | rebase | `REBASE_HEAD` | `REBASE_HEAD^` |
   | cherry-pick | `CHERRY_PICK_HEAD` | `CHERRY_PICK_HEAD^` |

   Then diff the base against the incoming side for `CHANGELOG.md` only, and list its
   merged PRs/commits:

   ```bash
   git log --first-parent <merge-base>..<incoming> --pretty='%h|%ad|%s' --date=short
   git diff <merge-base> <incoming> -- CHANGELOG.md
   ```

   Ignore incoming lines that merely restate entries the target side already has (compare
   by ticket/PR/issue number where available, not raw text — wording often drifts).

3. **Resolve the hunks keeping the side that matches the repo's current convention** (step
   1). Strip the conflict markers so that structure survives intact. Do not leave an
   older-format section anywhere in the file — fold it in per step 4 instead.

4. **Convert each genuinely new change into an entry matching the file's existing style**,
   inserted in the right place (its release/month/unreleased section per the detected
   grouping) and the right category, newest first within that grouping. Reuse the exact
   citation style already in use nearby (PR number, ticket prefix, hash, date — whichever
   the repo actually does) — pull the real values from the merge commit on the incoming
   side (step 2), never from memory or a template. One PR usually collapses to one bullet;
   give a second bullet only when a distinct facet belongs in another category (e.g. a
   security fix inside a feature PR). Condense multi-paragraph older-format prose to the
   user/operator-visible effect — implementation detail belongs in the PR, not the
   changelog.

5. **Verify ordering mechanically** before committing, adapted to the grouping you found in
   step 1 (per-version, monthly, or otherwise — the check below assumes dated entries or
   section headers; adjust the regex if this repo's entries aren't dated inline):

   ```bash
   python3 - <<'EOF'
   import re
   sec=None; last=None; errs=[]
   for i,line in enumerate(open("CHANGELOG.md"),1):
       if line.startswith(("## ","### ")): sec=line.strip(); last=None; continue
       m=re.search(r'(\d{4}-\d{2}-\d{2})[^)]*\)\s*$', line)
       if m:
           d=m.group(1)
           if last and d>last: errs.append(f"L{i} {sec}: {d} after {last}")
           last=d
   print("\n".join(errs) if errs else "OK")
   EOF
   ```

   If the repo has its own Python (`uv run python`, a `venv`, etc.), use that interpreter
   instead of a bare `python3`. Also confirm no conflict debris remains - all three markers,
   not just the opening one, because an edit that deletes a `<<<<<<<` and leaves the
   `=======` below it passes a check that only looks for openings:
   `grep -cE '^(<{7}|={7}|>{7})' CHANGELOG.md`.

6. Stage the file and finish whatever operation is actually in progress - this conflict
   arrives from a rebase and a cherry-pick as often as from a merge, and each is continued
   differently:

   | Present in `.git/` | Operation | Continue with |
   |---|---|---|
   | `MERGE_HEAD` | merge | `git commit` |
   | `REBASE_HEAD` | rebase | `git rebase --continue` |
   | `CHERRY_PICK_HEAD` | cherry-pick | `git cherry-pick --continue` |

   ```bash
   git rev-parse -q --verify MERGE_HEAD || git rev-parse -q --verify REBASE_HEAD \
     || git rev-parse -q --verify CHERRY_PICK_HEAD
   ```
