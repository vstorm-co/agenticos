# ai.classify

Puts a text in exactly one of the step's categories and continues down that
category's port, or `other` when none fits. Each category is a port id and a
sentence saying what belongs in it. The model answers with an object whose
`category` is an enum of the names plus `other`, and a one-sentence `reason`,
so it cannot pick a branch the graph has no wire for; an answer outside the
enum fails the step with `STRUCTURED_OUTPUT_MISMATCH`.

The text is handed on unchanged beside the category and the reason. It runs as
the step's own agent through `_model_step`, under the same limits and checks as
every model step.

## Ports

| Port | When |
|---|---|
| `in` | always |
| one per category | the model chose it |
| `other` | no category fits |
| `unsure` | only with `min_confidence`: the model's confidence was below it |

## Confidence and the unsure port

Set `min_confidence` (0 to 1) and the model is also asked how sure it is that
the category is right. The output then carries `confidence` and `unsure`, the
same fields `decide.*` reports. Below the minimum the step leaves by `unsure`
with the category still on the output; at the minimum it leaves by the category.
The number is the model's own report, not a probability, and not calibrated: a
model tends to say 0.8 to 0.95 whatever it knows. An answer without a number
never leaves by `unsure`. Without a minimum nothing about confidence is asked,
`confidence` is null and the step has no `unsure` port. A category cannot be
called `unsure` while the step has a minimum.
