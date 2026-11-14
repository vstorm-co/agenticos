# Connected chat apps

These tools are opt-in grants on each active agent/bot exposure, separate from
lookups in the current inbound conversation. Granting an action reaches all
channels the bot has joined. It does not join channels or change membership.

The runner injects only granted tools for an identified actor. The service
rechecks the actor, agent, binding, bot and destination on every call. Read pages
are bounded; provider failures do not become empty search results. Sending is an
external write and uses the normal approval gate. An uncertain send is not retried.

No bot credential is placed in a model prompt, tool result or persisted run state.
