# Follow-ups

Next-step buttons come only from an explicitly selected separate model. An empty
`model_profile_id` disables them. The main agent keeps `propose_setup` for setup
cards and receives instructions to leave next steps to the background writer.

After the saved assistant message commits, `services/follow_ups.py` opens its own
session, rechecks the run owner's current membership and key scope ceiling, and
runs a tool-free model with the question and answer. It uses a separate governed
run for budget checks, tracing privacy and cost settlement. No live RunContext,
ledger, ORM object or request session crosses the handoff. The channel router
starts its writer after delivering the main answer.

Suggestions are optional: four concurrent writers per process, a 15-second model
bound, at most two requests and 512 output tokens, no retry. Shutdown or capacity
can cost the buttons, never the answer. Writes and late room events target the
saved assistant message; another turn remains independent. Stored calls retain
`suggest_next_steps` as their historical identity without offering it to the
main model. Selecting a step is an ordinary new message and grants no authority.
