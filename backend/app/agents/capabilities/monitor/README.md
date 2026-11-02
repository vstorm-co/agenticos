# Watch a command

A run owns up to four detached commands in its persistent sandbox shell. New
matching output is included as a transient note on following model requests.
Desktop DeviceWorkspace commands have a process tree limited to one shell call,
so start_monitor refuses them before launching anything.

Slots are reserved before awaiting startup. Output is read in bounded chunks,
matched incrementally and shown as a bounded preview. Cleanup sends TERM, waits
briefly and escalates to KILL. An unavailable shell leaves an explicit failed
stop instead of claiming success or deleting its logs.
