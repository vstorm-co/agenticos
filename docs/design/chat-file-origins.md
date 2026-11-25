# Chat file locations

The Files panel can choose between the agent workspace and project workspaces
retained by runs in the chat. The conversation's workspace-origins response names
each location and its exact default workspace ID. A selected path is always read
through that location's existing resource endpoint; equal names never cause a
search or fallback into another workspace.

Only the Files panel opts into origin selection. Existing conversation-default
consumers keep their existing contract. Local desktop folders keep their local
adapter. A successful, initially empty origin inventory keeps the legacy
conversation archive and its ZIP downloads. An inventory failure, revoked origin
or malformed project reference never activates that compatibility path.

Selection and content caches are scoped by session owner, organization,
conversation and origin. A terminal turn refreshes the inventory, file listing
and open preview. Moving a project workspace invalidates these queries too.
After a selected location disappears, its listing and preview are removed and the
person must explicitly choose another location. A changed server default cannot
silently redirect an already selected file.

Individual downloads use the chosen resource. ZIP controls are omitted for
explicit origins because the existing archive endpoint addresses only the
conversation default; using it for another selected origin could download the
wrong files. Inventory truncation and file-list truncation are separate notices.
