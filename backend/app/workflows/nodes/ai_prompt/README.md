# ai.prompt

Asks one of the organization's models something and hands the answer on. The
step writes its own instructions; the prompt is bound from the run. With
`structured_output_schema` the model answers with an object of that shape,
checked before the next step runs.

It has no tools, so it never waits on an approval. It runs as the step's own
agent through `_model_step`, so the step's `max_cost_usd`, the workflow's budget
and the organization's limit apply, its cost is booked on the workflow run, and
the run is in Activity. Publishing checks that the author may use the model.
