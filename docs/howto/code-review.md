---
title: "Review a change in a repository"
description: "Have an agent build a tiny git repository in its sandbox, then review one diff against the built-in code-review skill and check it finds both planted bugs at the right lines."
---

# Review a change in a repository

Give an agent a [sandbox](../sandbox.md) and the shipped `code-review` skill,
and have it set up a small git repository, then review one commit's diff
against it. The diff carries two planted bugs — an off-by-one and an
unhandled `None` — at file:line locations you can check by hand. This is a
procedure to run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile and a
  registered [sandbox connection](../sandbox.md) whose default runtime is
  `workbench` — it carries `git`.
- The `code-review` skill, which ships with every organization; see
  [Skills](../skills.md#getting-skills-into-an-organization).
- Nothing else attached: the repository is created inside the sandbox by the
  agent itself, from the exact file contents in the prompt below.

## Prepare the input

No file to attach here — the "repository" is two small Python files the agent
writes itself, at your instruction, so you control exactly what the diff
contains. Version 1 is a plain checkout calculator:

```python
# utils.py (version 1)
def compute_total(prices):
    total = 0
    for p in prices:
        total += p
    return total


def find_discount_tier(count):
    tiers = [(10, 0.05), (20, 0.10), (50, 0.15)]
    for threshold, rate in tiers:
        if count >= threshold:
            return rate
    return 0.0
```

```python
# main.py (version 1)
from utils import compute_total, find_discount_tier


def checkout(cart):
    prices = [item["price"] for item in cart]
    total = compute_total(prices)
    rate = find_discount_tier(len(cart))
    return total * (1 - rate)
```

Version 2 adds a member discount and an `apply_discount` helper, with two
planted bugs: `main.py`'s new `member_rate` parameter defaults to `None` and
is used without a check, and `utils.py`'s `apply_discount` discounts every
item including the most expensive one and then appends that same item again,
double-counting it.

```python
# utils.py (version 2, adds apply_discount)
def apply_discount(prices, rate):
    """Discount every item except the single most expensive one."""
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    discounted = [sorted_prices[i] * (1 - rate) for i in range(n)]
    discounted.append(sorted_prices[-1])
    return discounted
```

```python
# main.py (version 2)
from utils import compute_total, find_discount_tier, apply_discount


def checkout(cart, member_rate=None):
    prices = [item["price"] for item in cart]
    tier_rate = find_discount_tier(len(cart))
    discounted_prices = apply_discount(prices, tier_rate)
    total = compute_total(discounted_prices)
    return total * (1 - member_rate)
```

Reference: the diff between the two versions has exactly two real defects —
`main.py`'s `return total * (1 - member_rate)` raises `TypeError` whenever
`member_rate` is left at its default, and `utils.py`'s `apply_discount`
returns one item too many because its loop already includes the last index
before that same item is appended again. Neither `compute_total` nor
`find_discount_tier` changes between versions, so a correct review says
nothing about them.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Files & shell**. Choose **Container**, select
   your sandbox connection and the `workbench` runtime, and keep the
   conversation scope.
3. Enable **Skills** and bind `code-review`.
4. Set a budget for the trial — the recorded run used about 40 steps and cost
   about 0.18 USD, mostly from the repeated shell approvals.
5. Set the instructions below, then **Publish**.

```text
You review a change in a git repository using the bound code-review skill.
Follow that skill: read the whole change before commenting, say what is wrong
and why it matters, and separate what blocks from what does not.
Only report issues that are actually in the diff. Do not report a problem in a
line the diff did not touch.
Cite every finding as file:line and give a concrete fix.
```

## Run it

Open a new chat and paste the two versions above with instructions to set up
the repository and review the change:

```text
Set up a tiny git repository in your workspace and review one change in it.

1. Create a directory `grocery_calc`, write utils.py and main.py exactly as
   given above (version 1), then git init, configure a throwaway user, and
   commit them as the initial version.
2. Replace both files with version 2 exactly as given above, and commit that
   as a second commit.
3. Run `git diff HEAD~1 HEAD` to get the exact change, then review that diff
   using the bound code-review skill. Report every real defect the diff
   introduces, each as file:line with a concrete fix. Do not report anything
   about a line the diff did not change.
```

Each `execute` call the agent makes — `git init`, each commit, the diff —
shows **Tool approval required** in the chat. Read the command and
**Approve** each one; the run continues from where it stopped. To skip this
for a trusted test agent, change the approval setting of `execute` in the
Builder. See [approvals](../governance.md#approvals).

## Check the result

| Check | Reference |
| --- | --- |
| Unhandled `None` found | `main.py:9`, `return total * (1 - member_rate)` crashes when `member_rate` is left at its `None` default |
| Off-by-one found | `utils.py:20-21`, the comprehension already covers every index including the last, then that item is appended a second time |
| Both cited as file:line | Not just "there's a bug in apply_discount" |
| Fix is concrete | A corrected snippet, not just a description of the problem |
| Unchanged code | No finding about `compute_total` or `find_discount_tier`, which the diff did not touch |
| Blocking vs. not | The two bugs are marked blocking; anything stylistic is prefixed "nit" |

Read the diff yourself before trusting the review — `git diff HEAD~1 HEAD` in
the workspace's files panel shows exactly what the agent reviewed.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent loaded the
    `code-review` skill, then `read_skill_resource` for the skill's
    `checklist.md` and `review-comment.md`, then wrote both files, committed
    twice and ran the diff — three `execute` calls, each parked for approval.
    After approval it answered with three blocking findings and one nit.

    It cited `main.py:9` for the `TypeError` on a missing `member_rate` with
    a two-line fix, and `utils.py:20-21` for the double-counted item with a
    corrected `apply_discount`, matching both planted bugs exactly. It also
    flagged the diff as untested, following the skill's checklist rule that a
    behaviour change needs a test. It said nothing about `compute_total` or
    `find_discount_tier`. Cost: 0.18 USD across 40 steps, most of it the three
    approval round trips.

## When it goes wrong

- **The agent says it has no shell.** The capability uses **Files** instead
  of **Container** — switch to Container and pick the `workbench` runtime.
- **The run stops after `git init` or a commit.** It is waiting for approval
  of `execute`. Open the chat, or the **Approvals** tab in **Activity**.
- **The review reports something about unchanged code.** Tighten the
  instructions: it must review only what `git diff` shows, not the whole
  file.
- **A finding has no file:line.** Ask it to re-read the checklist's own
  comment templates, which always name a location.
- **The first turn is slow.** The `workbench` image is building; later
  sessions reuse it. See [the sandbox](../sandbox.md#when-a-build-is-paid-for).

## Record the trial

Keep the exact two versions, the diff, the review, the agent version and each
approved command in Activity. A person still decides whether the fixes are
right and whether "no test for this" should actually block the merge — the
skill states that rule, but applying it to a real pull request is a person's
call, same as [the local review standard](../code-review.md) this project
follows on its own PRs.

## Next steps

Point the same agent at a sandbox with network access and have it review a
diff from a cloned public repository instead of one you dictate — the
`workbench` runtime has `git` and a network, so `git clone` works the same
way `git diff` did here.
