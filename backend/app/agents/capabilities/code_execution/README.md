# Code execution

Exposes `run_python`, evaluated in the Monty sandbox: no network, no filesystem,
a restricted stdlib subset.

That restriction is what makes the capability safe to grant broadly. A general
sandbox has remote code execution as its failure mode, which is why `code:execute`
is a scope an organization grants deliberately rather than a default.
