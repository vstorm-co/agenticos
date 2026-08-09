# Charts

Exposes one tool, `create_chart`, which returns a `ChartSpec` as JSON. Nothing
draws a picture here: the web chat renders that spec interactively with Recharts,
and the channel adapters render the same spec to a PNG for Slack and Telegram.

## Layout

| File | Holds |
|---|---|
| `_spec.py` | The wire format - `ChartType`, `ChartSeries`, `ChartStyle`, `ChartSpec`, `parse_chart_spec()` |
| `_toolset.py` | `ChartsToolset`: the one public tool method, its prompt, and the private helpers it uses |
| `_capability.py` | The `Charts` dataclass and `get_toolset()` |
| `__init__.py` | Registry entry and exports |

**Why `_spec.py` is separate.** `app/services/channels/` parses chart results to
decide whether a tool result is a picture worth sending. That is a consumer of
the format, not of the agent: it imports `charts._spec` and nothing follows it in
- no toolset, no capability, no tool prompt. Keeping the format in a leaf module
is what makes that true rather than merely intended.

**Why the prompt lives on the method.** The tool description is the highest-value
text in this package - it is what the model actually reads. Before this split
there were three versions of it in two files (one on the implementation, one on a
dead wrapper, one nested inside the toolset builder), and only the innermost one
reached the model. A public method on `ChartsToolset` has exactly one docstring
and it is the tool description, so there is nowhere for a second one to hide.

Two instructions in it are load-bearing and should survive editing:

- **Do not repeat the JSON back to the user.** Without it, models narrate the
  payload - unreadable, and the user is already looking at the chart.
- **The scatter shape.** Numeric x values, and a series carrying its own
  `x_values` when two groups of points sit at different positions on the axis.

**Why the numbers arrive as columns.** `create_chart` takes `x_values` and one
`values` list per series rather than a `data` list of rows. That is not a
stylistic preference: `data: list[dict[str, Any]]` reaches the model as an array
of objects with **no declared properties**, so the only row the schema promises
is valid is `{}`. Which is what arrived - twice, from a model that had filled in
the series labels, the hex colours, the axis titles and the x-axis key, and then
sent one empty row. A list of numbers is expressible in a JSON Schema, so the
same mistake has nowhere to live. The row format is unchanged on the wire:
`_rows` zips the columns back into one row per x value, because that is what
Recharts and the PNG renderer read.

## Configuration

None. What a chart looks like is decided per chart by the model (`chart_type`,
`series`, `style`), and palettes and defaults belong to the surface that renders
it. A per-agent setting would be a third opinion with no tiebreaker.

## Failures

Bad arguments raise `ModelRetry` naming what was wrong - an empty axis, no
series, or a series holding a different number of values from the axis it is
plotted against - so the model corrects itself instead of the run ending with an
error string persisted as a chart result.

`ChartSpec` refuses a chart with nothing in it too, which is belt and braces now
that the tool cannot express one: it also guards a spec reassembled from a
persisted result, which is how the channel renderer meets the format.
