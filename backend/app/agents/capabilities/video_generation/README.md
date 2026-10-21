# Video generation

Exposes one tool, `generate_video`, which makes a short video from a description
and returns a reference to the clip. The video is made by the provider the binding
chose - Google Gemini Omni, ByteDance Seedance on BytePlus, xAI Grok Imagine or
Alibaba Wan today - stored organization-scoped, and played to the user by the
interface, exactly where a generated image would be shown (#2260).

## Layout

| File | Holds |
|---|---|
| `_toolset.py` | `build_video_toolset`: the tool, its prompt, the starting image, the budget check, the metering and the storage; plus `GeneratedVideo`/`parse_generated_video`, the wire format |
| `_capability.py` | The `VideoGeneration` dataclass and `get_toolset()` |
| `__init__.py` | `VideoGenerationConfig`, the registry entry, the secret and exports |

What is *offered* - providers, models, what each can make, prices - is the
catalog, `app/core/catalog/video_models.json` read by
`app/services/video_models.py`. How each provider is *called*, polled and
downloaded from is `app/services/video_generation/`.

## Why the same shape as image generation

A person asking for a clip expects what they get when they ask for a picture: a
file in the conversation, saved where the agent can build with it. So the clip goes
through `app/agents/capabilities/_generated.py`, the helper `generate_image` and
`generate_speech` use, and the Builder panel is the same provider and model selects
with the resolution, shape and length beside them.

A clip can start from an image: the `filename` `generate_image` returned in the
same run, or a workspace path. "Draw a logo, then animate it" is two calls and
nothing to upload. The generated store is organization-wide and an agent can be
driven by somebody who is not a member - a channel participant, a widget visitor -
so it is reached only for a file this run's own tools stored
(`AgentDeps.generated_files`, written by `store_generated`), never by a file name
alone or by any tool's text claiming one. An image from an earlier turn is reached
through its workspace copy under `output/`. The image is typed by its bytes, not
its name.

## A job, not a request

Three of the four providers take a job and are polled for it; Gemini answers in
the request. Either way the tool call waits for the clip, with the step's spinner
running, the way a picture is waited for - a minute or several. The wait is
bounded by `timeout_seconds`. A job past it is cancelled where the provider
allows it (BytePlus, while it is still queued), and the call is answered, not
retried: xAI and Alibaba document no cancel, so their job may still finish and be
billed, and a second attempt would be billed again.

It is not a background job that outlives the run. A cancelled run cancels the
wait, and the clip - if the provider finishes it - is not collected. That is the
trade for behaving exactly like image generation; a durable job would be a Prefect
flow and a decision of its own.

## Cost

Every provider bills by the second, at a rate set by the resolution, so the
catalog holds a dated price per second per resolution and the tool asks the budget
with the clip's price before submitting. Gemini Omni decides its own length, so a
clip there is priced at the model's longest before the call - the most it can
cost - and booked at that, because Gemini reports no length. The others report the
length they made, and that is what is booked. A job that fails or times out is
not booked: none of the four reports a charge for one, so a figure here would be a
guess - which is the gap to check against a provider's console.

## What it deliberately does not do

- **No OpenAI.** The Sora 2 API was shut down on 2026-09-24, and Azure's last
  `sora-2` retired on 2026-10-15. A future model is one client and one entry.
- **No negative prompt, no seed, no last frame.** Not every provider here has
  them, and a field a provider ignores is a setting with no effect.
- **No video input or extension.** A clip is made from words and, optionally, an
  image.

## Failures

| Failure | Answer |
|---|---|
| Empty prompt, a length or shape the model does not make, an unreadable image | `steer` - the model can fix its call |
| Content policy refused the prompt or image | `steer` - describe the shot differently |
| Provider refused the request, rate limiting, or down | `steer` - worth one more try |
| Key refused, model dropped from the catalog, budget spent | Returned - only the author or the operator can fix it |
| Not ready within `timeout_seconds` | Returned - a retry is billed again |

The provider's own error text is logged where it is received and never reaches the
model.
