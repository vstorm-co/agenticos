# ai.extract

Pulls the fields `output_schema` names out of a bound text and hands them on as
`data`. The model is told to take values as written and to leave a field out
rather than guess one, and it answers with an object of the schema's shape;
text instead of an object fails the step with `STRUCTURED_OUTPUT_MISMATCH`.

A document is read with `text.extract` first. It runs as the step's own agent
through `_model_step`, under the same limits and checks as every model step.
