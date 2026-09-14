---
name: resolve-changelog-conflict
description: Resolve a merge conflict in CHANGELOG.md by keeping the monthly format and converting the other side's entries into it. Use whenever git reports a conflict in CHANGELOG.md, or when entries in the old single-[Unreleased] format need folding into the monthly sections.
---

# Resolve a CHANGELOG.md conflict

`CHANGELOG.md` uses monthly sections (see the file header and the Changelog
rule in `CLAUDE.md`); merging to `main` is the release. Conflicts happen when
two branches append near the same lines, or when a branch still carries the
old single-`[Unreleased]` format. The resolution is never "pick a side
wholesale": keep the monthly-format structure, then re-express the other
side's *new* entries inside it.

## Steps

1. **Identify what the other side actually adds.** Diff the merge base against
   the incoming branch for CHANGELOG.md only, and list its merged PRs:

   ```bash
   git log --first-parent <merge-base>..<incoming> --pretty='%h|%ad|%s' --date=short
   git diff <merge-base> <incoming> -- CHANGELOG.md
   ```

   Ignore incoming lines that merely restate entries the monthly file already
   has (compare by ticket/PR number, not text).

2. **Resolve the hunks keeping the monthly-format side.** Strip the conflict
   markers so the monthly structure survives intact. Do not keep old-format
   paragraphs anywhere in the file.

3. **Convert each genuinely new change into the standard entry** and insert it
   in its **merge month** section, right category (Added / Changed / Fixed /
   Removed / Security), newest first:

   ```markdown
   - **Bold headline** — one or two sentences of user/operator-visible
     effect. (RDRL-xxx, #PR, `mergehash`, YYYY-MM-DD)
   ```

   Ticket, PR, hash, and date come from the merge commit on the incoming side
   (step 1), never from memory. One PR usually collapses to one bullet; give a
   second bullet only when a distinct facet belongs in another category (e.g.
   a Security fix inside a feature PR). Condense multi-paragraph old-format
   prose to the visible effect — implementation detail stays in the PR/ADR.

4. **Verify ordering mechanically** before committing:

   ```bash
   uv run python - <<'EOF'
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

   Also confirm no conflict markers remain: `grep -c '^<<<<<<<' CHANGELOG.md`.

5. Stage and complete the merge commit as usual.
