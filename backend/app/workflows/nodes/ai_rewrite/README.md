# ai.rewrite

Summarizes, translates or rewrites a bound text. `task` picks the job; `length`
sets a summary's size, `language` the language to answer in (required to
translate), and `style` how it should read. The settings become the model's
instructions and the text its prompt, and the answer is the result alone.

It runs as the step's own agent through `_model_step`, under the same limits and
checks as every model step.
