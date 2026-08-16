# Image generation

Exposes one tool, `generate_image`, which draws an image from a text prompt and
returns a reference to it. The bytes are produced by a dedicated image model this
capability calls itself, stored organization-scoped, and shown to the user by the
interface.

## Layout

| File | Holds |
|---|---|
| `_toolset.py` | `build_image_toolset`: the `generate_image` tool, its prompt, the subagent run, the metering and the persistence; plus `GeneratedImage`/`parse_generated_image`, the wire format |
| `_capability.py` | The `ImageGeneration` dataclass and `get_toolset()` |
| `__init__.py` | `ImageGenerationConfig`, the registry entry, the secret and exports |

## Why a subagent, not native image generation

Pydantic AI ships an `ImageGeneration` capability with two paths: the model's own
**native** image tool, and a **local** fallback that delegates to a subagent. This
capability is neither of those directly, and the reason is what it has to do with
the result.

- **Native** image generation is offered by only a few models, and it is
  delivered as a provider tool whose output is part of the main model response.
  That response never passes through this code, so a natively generated image
  cannot be stored tenant-scoped, cannot be written into the workspace, and its
  cost is whatever the run's budget guard already prices for the main request.
  Useful, but not something a platform can store, serve or build with.

- The library's **local** tool (`image_generation_tool`) runs a subagent and
  returns `result.output` - **discarding `result.usage()`**. That is the invisible
  spend #16 is about: real money on a provider key, booked to no ledger.

So the subagent is run here rather than reused, which is what lets its usage be
booked to the run's ledger (`record_ambient_usage`, inside the `metered_by` block
the runner holds open) and its output be stored and placed in the workspace. The
cost of running it here is one Pydantic AI `Agent` construction per call; the cost
of not is spend nothing can see.

## Where the image goes

Two places, and they answer different needs:

- **Always** persisted organization-scoped via `app/services/generated_media.py`
  and returned as a `url` the interface renders. This is the delivery path, and it
  works for every agent.
- **When a workspace is open** (an agent with the `sandbox` capability), the same
  bytes are also written under `/output`, so a later `execute` step can build with
  the image it just made - assemble a PDF, a slide, a page. The workspace backend
  arrives as a build resource (`WORKSPACE_BACKEND_RESOURCE`); an agent without one
  still generates and shows images, it just has nowhere to build.

Storage is **organization-scoped, not per-user** - wider than a chat upload,
because there is no row recording who produced an image, so the tenant is the
boundary that can be enforced without one. `docs/reference/capabilities.md` and
the `generated_media` docstring state the trade;
[#55](https://github.com/vstorm-co/agenticos/issues/55) is where a per-run record
would tighten it, inheriting this directory convention and the serving route.

## Configuration

`model` is the only required choice - which image model draws, and therefore
which provider the API key belongs to. `quality`, `size`, `background`,
`output_format` and `aspect_ratio` are optional; left unset, the provider applies
its own defaults, so turning the capability on is enough to generate. The API key
is a `SecretRequirement`, so publishing an agent that binds this capability
without one is refused while somebody is looking at the form rather than at a
failed run.

## Failures

A refusal or misbehaviour from the image model comes back as `ModelRetry` naming
what went wrong, so the model rephrases rather than the turn ending on an error
string. A build with no key (a preview, a test) yields a tool that refuses the
same way before spending or storing anything - the published path never reaches
it, because the secret is required.
