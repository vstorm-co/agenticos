---
name: pr-comments
description: Use this skill when user asks to address PR review comments. It will fetch all comments, present them in a structured format.
user-invocable: true
---

# Skill: PR Review Comments

Fetch all review comments from a PR, present them in a structured format, then systematically address each one.

## Inputs

Determine from conversation context or user's message:
- **PR number or URL** — if not given, detect from current branch: `gh pr view --json number -q .number`
- **Include nits** — default: skip. User may say "include nits"
- **Include outdated** — default: skip. User may say "include outdated"
- **Include resolved** — default: skip. User may say "include resolved"
- **List only** — if user just wants to see comments without fixing

## Steps

### 1. Fetch all review threads

IMPORTANT: Use GraphQL, NOT REST. The REST endpoints (`pulls/N/comments`, `pulls/N/reviews`) do NOT return `isResolved` or `isOutdated`. Only GraphQL has this data.

```bash
OWNER=$(gh repo view --json owner -q .owner.login)
REPO=$(gh repo view --json name -q .name)
```

Run this exact query (replace NUMBER with the PR number):

```bash
gh api graphql -F owner="$OWNER" -F name="$REPO" -F pr=NUMBER -f query='
query($owner: String!, $name: String!, $pr: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      title
      url
      comments(first: 100) {
        nodes {
          body
          author { login }
          createdAt
          url
        }
      }
      reviews(first: 100) {
        nodes {
          body
          author { login }
          state
          url
        }
      }
      reviewThreads(first: 100) {
        nodes {
          isResolved
          isOutdated
          path
          line
          startLine
          resolvedBy { login }
          comments(first: 20) {
            nodes {
              body
              originalLine
              author { login }
              createdAt
              replyTo { id }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}'
```

Paginate if `hasNextPage` is true by adding `-F after="$CURSOR"` and updating the query signature. Re-use the same `nodes` selection set as the first query (shown here so the snippet is directly executable). Only `reviewThreads` paginates; `comments` and `reviews` are capped at 100 and already fully read by the first call, so ignore their repeated nodes on paginated pages.

```bash
gh api graphql -F owner="$OWNER" -F name="$REPO" -F pr=NUMBER -F after="$CURSOR" -f query='
query($owner: String!, $name: String!, $pr: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      comments(first: 100) {
        nodes {
          body
          author { login }
          createdAt
          url
        }
      }
      reviews(first: 100) {
        nodes {
          body
          author { login }
          state
          url
        }
      }
      reviewThreads(first: 100, after: $after) {
        nodes {
          isResolved
          isOutdated
          path
          line
          startLine
          resolvedBy { login }
          comments(first: 20) {
            nodes {
              body
              originalLine
              author { login }
              createdAt
              replyTo { id }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}'
```

### 2. Filter threads

| Condition | Default | Include when |
|-----------|---------|-------------|
| `isResolved: true` | Skip | user asks for resolved |
| `isOutdated: true` | Skip | user asks for outdated |
| Nit comment | Skip | user asks for nits |

**Nit detection**: first comment body starts with `nit:`, `nit -`, `nitpick` (case-insensitive, first 50 chars).

### 3. Present in unified format

`reviewThreads` are per-file/per-line, so they group by path. The two other sources are not anchored to the diff, so present each as its own section:

- **Top-level conversation comments** — `pullRequest.comments.nodes` (`IssueComment`s from the Conversation tab).
- **Review summary bodies** — `pullRequest.reviews.nodes` with a non-empty `body` (the note left alongside Approve / Request changes / Comment). Skip reviews whose `body` is empty — those carry only inline threads, already covered above.

```
## PR #<number>: <title>
<url>

**<N> actionable threads** (filtered: <X> resolved, <Y> outdated, <Z> nits)

---

### Inline threads

#### Thread 1 · `<path>`:<line> · @<author>
> <comment body>
>
> Reply by @<reply_author>:
> <reply body>

#### Thread 2 · `<path>`:<line> · @<author>
> <comment body>

---

### Conversation comments

#### @<author> · <createdAt> · <url>
> <comment body>

---

### Review summaries

#### @<author> · <state> · <url>
> <review body>
```

Group inline threads by file path, order by line number within file.
Mark `[outdated]`, `[resolved by @login]`, `[nit]` if included via flags.
Omit the "Conversation comments" or "Review summaries" section entirely when it has no entries.

### 4. Stop here if user only wants to list

### 5. Plan fixes

Before touching code:
1. Read each file mentioned in the threads
2. For each thread classify: **fix** (actionable), **skip** (question/discussion), or **ask** (unclear)
3. Present the plan and wait for user confirmation

### 6. Apply all fixes

For each fix:
1. State which thread you're addressing
2. Apply the fix (Edit tool)

After all fixes are applied:
1. Run the project's verification command (`uv run pre-commit run --all-files` for this repo; substitute the equivalent in other repos)
2. If it fails → fix before committing
3. Commit all fixes together: `fix: Address PR review comments`
4. Push to remote

**All fixes go in one commit.** No per-thread commits.

### 7. Summary

```
Fixed: N · Skipped: M · Needs input: K
Commit: <hash> <message>
```

## Rules

- Read the target file before making any fix
- Run the verification command after all fixes are applied, not per fix
- All fixes go in a single commit
- If a comment is ambiguous, ask rather than guess
- If a comment suggests a large refactor, flag it first
