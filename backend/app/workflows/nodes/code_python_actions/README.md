# Python with actions

A script reads `args`, calls the workflow actions selected for this step, and
hands its last expression to the next step as `result`. An alias is a regular
function with keyword arguments matching the action's input fields; its return
value is the action's JSON output. Ordinary data fields that the action marks bindable may also be
passed by name. The versioned binding fixes the connection and credentials;
keyword arguments cannot replace those settings.

The interpreter has no mounts, network client or platform credentials. At each
call it yields to the workflow engine, which owns the action, its approvals,
its retry policy and its budget. A checkpoint is private interpreter state,
not the step output; an unreadable checkpoint fails rather than restarting the
script from source. Calls are sequential, at most 100 per script. Triggers and
workflow outputs stay on the graph.
