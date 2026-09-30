# flow.resume_link

**Resume link**: hand on `url`, the address that resumes this run's Wait steps
waiting for a call. A step before the Wait sends it where the answer should come
from - an approver's message, a partner's callback URL - and a `POST` to it wakes
the Wait with what was sent.

## Why a step and not a field of the run

A binding reads the output of a step that ran before it. The link has to reach a
message or a request sent *before* the Wait, so it is the output of a step of its
own, placed there, rather than something the Wait hands on after it was called.

## Why nothing is stored for it

The link is the run's id and a MAC of it under the deployment's `SECRET_KEY`
(`app.services.workflow_execution.resume_link`): the same from every Resume link
step of a run, no use for any other, and checked in constant time. Holding it is
what lets a caller resume the run, so it is sent only where the answer should come
from. Rotating `SECRET_KEY` makes every link handed out before it fail.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | nothing; it only orders the step |
| `out` | output | `ResumeLinkOutput` | `url` |
