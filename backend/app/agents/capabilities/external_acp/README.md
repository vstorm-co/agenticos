# External ACP agent

A separately selectable delegation capability reusing the coding agent's Desktop
ACP pipe, session isolation, budget admission, streaming, cancellation and unpriced
usage records. It adds no background queue or A2A service.

Only a local registration ID is stored in the published spec. The Desktop owner
registers an absolute program path and argument array and approves native launch.
No command, environment, credential or account token comes from the server. The
program manages its own login and model; changing that account requires removing
and registering it again to discard continuation state.

Custom programs run with local account access. Read-only confinement is not
claimed; enable Human approval to ask before handing over each task. ACP native
tools belong to that program; platform tools are not forwarded. Unsupported ACP,
login requirements and missing programs fail explicitly. A session is resumed
only when the program declares support. This is delegation, not a primary runtime.
