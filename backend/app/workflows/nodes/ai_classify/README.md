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
