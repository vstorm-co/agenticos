# Visuals

Exposes three tools. `draw` puts a drawing in the conversation - an SVG diagram,
a Mermaid flow, or a whole HTML document for anything interactive, `<canvas>` and
three.js included. `revise_visual` changes one by exact replacements, and
`read_visual` reads one back as it now is.

## Layout

| File | Holds |
|---|---|
| `_toolset.py` | `VisualsToolset`: the three tools and their prompts, `content_problem` (what is refused before anybody sees it), and rebuilding a visual from its call and its revisions |
| `_capability.py` | The `Visuals` dataclass: the toolset, and the instruction naming the conversation's earlier visuals |
| `__init__.py` | The registry entry and exports |

The frame, the library set and the document a visual becomes are
`app/services/visual.py`'s, beside the apps it shares them with.

## A visual is an app that has not been saved

The drawing is the `content` argument of the call. The console reads it while it
streams - `tool_call_delta` - and posts it into a frame, so it grows on screen as
it is written. The transcript stores the call with its arguments, so a reload and
a shared thread draw it again from there. There is no table of visuals and no
copy of the bytes anywhere else.

The frame is one fixed page on the content origin
(`/api/v1/artifact-content/visual-frame`), served with the very policy an app's
page gets: an opaque origin, no `allow-same-origin`, no popups, no forms,
`connect-src 'none'`, nothing remote but the deployment's own library set. A
drawing is model-written script that may have read hostile input, so it gets
exactly the app sandbox and not a second, weaker one.

Scripts run once, when the call is complete. While it streams the frame morphs
the markup in place with every script and `on*` handler removed, and when it is
done it replaces its whole document with the finished one, which is the only way
an import map and module scripts behave as they will once the same bytes are
saved as an app.

## Why earlier visuals are named, not replayed

An earlier turn reaches the model as its text alone, so the drawings of earlier
turns are not in its context - which is right, since one can be megabytes and it
would be paid for on every later request. The capability's instruction names them
instead, by id and title, once per run; `read_visual` brings one back when the
model needs its text to revise it. The ids are the provider's tool-call ids,
looked up within the run's own conversation and nowhere else.

## Deliberately not side-effecting

A drawing changes nothing outside the conversation and is shown only to whoever
can read it. Saving one as an app is a person's decision in the console, or the
agent's through `publish_artifact`, which has its own rules.
