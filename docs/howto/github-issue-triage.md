---
title: "Triage new GitHub issues automatically"
description: "Fire an agent the moment an issue is opened, have it propose a priority and labels from the delivery alone, and test the trigger by signing a delivery yourself."
---

# Triage new GitHub issues automatically

Wire an [event trigger](../triggers.md) to a repository's `issues` webhook so a new issue reaches an agent the moment it is opened, and have the agent propose a priority, labels and a duplicate check from the delivery text. This page tests the trigger half on its own, by signing a synthetic delivery and posting it straight to the webhook - no GitHub account is used. This is a procedure to run, with one recorded run as a reference for that half. Labelling or commenting back on the issue needs a GitHub connection this environment does not have, and is not run here.

## What you need

- A [running installation](../install.md) with a model profile.
- To fire this for real, a repository you can add a webhook to (the **GitHub** OAuth App source) or a GitHub App registered for your organization (**GitHub (App)**) - see [two ways to connect GitHub](../triggers.md#two-ways-to-connect-github-and-how-to-tell-which-you-are-running). Neither is set up for the check below.
- To let the agent actually label or comment, a [GitHub MCP connection](../mcp.md#development) (token auth) or the GitHub App's own write permissions, bound to the agent - also not set up here.

## Prepare the input

A trimmed but realistic `issues` webhook payload for a fictional repository, small enough to check the triage against by hand:

```json
{
  "action": "opened",
  "issue": {
    "number": 42,
    "title": "Export button does nothing on Safari",
    "html_url": "https://github.com/acme/widgets/issues/42",
    "body": "Steps to reproduce:\n1. Open the reports page in Safari 18\n2. Click Export as CSV\n3. Nothing happens, no download, no error in the console\n\nWorks fine in Chrome. This is blocking our weekly export for finance."
  },
  "repository": {"full_name": "acme/widgets"}
}
```

Nothing here is a real repository or a real report.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. Leave the Toolbox empty for this trial - it only needs to read a delivery and reason over it. **Date and time** is enough if you want the triage to reference today's date.
3. Set the instructions to the seeded template's own prompt, then **Publish**:

```text
You triage new GitHub issues from the delivery described in the task message.
Suggest a priority (low, medium, high) and one or two labels.
Say whether it looks like a duplicate of an existing issue, using only what the message gives you.
Flag immediately, in the first line, if it looks like a security report.
End with a short comment-ready summary a maintainer could paste onto the issue.
You have no tool to read the repository or post the comment yourself - say so if asked to do either.
```

This is the prompt behind **Triage the new issue** in the trigger templates (`GET /trigger-templates`), which pre-fills exactly this on a new **GitHub** event trigger.

## Set up the trigger

In **Routines → New event trigger → GitHub**, choose this agent, keep the default filter (fires on `opened` only) and paste the resulting webhook URL and signing secret into the repository's **Settings → Webhooks → Add webhook**, with content type `application/json` - see [a GitHub recipe](../triggers.md#a-github-recipe-5-minutes) for the exact fields. That step needs the repository, which this trial does not have.

## Run it

Without a repository to deliver from, sign a synthetic delivery yourself, exactly as [signing a delivery yourself](../triggers.md#signing-a-delivery-yourself) describes for the generic source - GitHub's own deliveries use the identical `HMAC-SHA256` scheme, only the header name changes:

```python
import hashlib, hmac, json, httpx

secret = b"<the trigger's signing secret>"
body = json.dumps(payload).encode()  # the fixture above
signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

httpx.post(
    f"{BASE}/api/v1/webhooks/triggers/github/{trigger_id}",
    content=body,
    headers={
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
    },
)
```

## Check the result

| Check | Reference |
| --- | --- |
| The signed POST | `202`, immediately |
| The run in Activity | Surface `schedule` (an event trigger fires the same way a schedule does), status completed |
| The triage | Names a priority and one or two labels, addresses the duplicate question, and is not flagged as a security report |
| The reply's last line | A short, comment-ready summary |
| Tool calls | None - this agent has no GitHub tool, so it only reasons over the delivered text |
| Asking it to post the label itself, in the same run's conversation | Says it has no tool to do that, rather than inventing one |
| The same payload signed with the wrong secret | `403`, before the run is ever considered |
| A delivery with `"action": "edited"` | `202`, and no new run - the default filter only fires on `opened` |

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The signed delivery answered `202`; a run appeared in Activity about ten seconds later on the `schedule` surface, cost 0.003861 USD, with the message the trigger appended: "A GitHub issue was opened in acme/widgets. Issue #42: Export button does nothing on Safari …".

    The reply: "**Not a security report.** Priority: High. Labels: `bug`, `browser-compatibility`. Duplicate check: Nothing in the provided information suggests this is a duplicate …", ending with a comment-ready paragraph naming the reproduction steps and suggesting a maintainer check `Blob`/`<a download>` handling in Safari. No tool calls were made. A delivery signed with the wrong secret came back `403` with `"Webhook signature did not verify"`; the same payload with `"action": "edited"` came back `202` with no new run.

## When it goes wrong

- **`403` on every delivery, real or synthetic.** The secret does not match, or the content type is not `application/json` - a form-encoded delivery signs different bytes than GitHub sent. GitHub's own **Recent Deliveries** tab on the webhook shows the exact request and response for a real repository.
- **`202` but nothing in Activity.** `202` means accepted, not finished, and also means "matched nothing" - an inactive trigger or a filtered-out action answers identically. Check the trigger's filter before assuming a bug.
- **A `GitHub (App)` trigger has no webhook to find in the repository's settings.** Expected - the App delivers to one shared URL per installation, not a URL per trigger. See [when a delivery arrives](../triggers.md#when-a-delivery-arrives).
- **The agent tries to comment and cannot.** This trial's agent has no GitHub tool on purpose. Adding one is a separate, deliberate step - see next.

## Record the trial

Keep the signed payload, the trigger's filter, the run in Activity and its reply. This only proves the trigger and the prompt; it does not prove labelling or commenting, which needs its own capability and its own review.

## Next steps

To let the agent act rather than only propose, bind a [GitHub MCP connection](../mcp.md#development) or the GitHub App's write permissions, and decide who reviews a label or a comment before it posts - MCP tools carry no per-tool approval of their own, so that review has to come from a person watching the run or from the chat's own **Ask about everything** mode, the same as [turning meeting notes into tasks](meeting-to-tasks.md). A trigger always runs as [the member who created it](../concepts.md#it-runs-as-a-person), so give that role to whoever should own a misfiring trigger, not to whoever happened to set it up.
