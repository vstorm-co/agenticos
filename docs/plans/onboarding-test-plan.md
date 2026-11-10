# Guided onboarding: regression and acceptance scenarios

Scope: PR #2808. Use disposable accounts and workspaces in a local environment.
Do not send invitations to real recipients or call paid models unless explicitly intended.
A demo or a model-setup reply must never be counted as a successful AI run.

## Personas and entry paths

| Scenario | Expected result |
|---|---|
| First account on a fresh installation | Application administrator can create a company workspace without using Personal. Deployment setup is offered. |
| Application administrator on an established installation | Existing agents and personal chat activity suppress the automatic first-use offer; opening onboarding explicitly still works. |
| Existing organization owner or administrator | Organization setup is available according to effective permissions; deployment-only settings remain unavailable. |
| New ordinary account with an organization | Profile, context and first-task guidance are offered without requiring administrative configuration. |
| Existing account joins a different organization | The new membership gets its own welcome, goal and completion state; the original organization's progress stays intact. |
| Invited account has no organization yet | The invitation can be accepted before selecting a workspace; onboarding opens in the joined organization. |
| Viewer or member with resource grants | Only accessible agents are shown; an explicit resource grant is respected without promoting the organization role. |
| Membership is revoked while onboarding is open | Requests fail with the normal access refusal; no state from another organization is rendered as a fallback. |

## Guided setup

| Scenario | Expected result |
|---|---|
| Create or choose a workspace | The next step opens automatically. Existing names, logos and fallback colors are used. |
| Edit organization or personal avatar | Upload and fallback colors work; neighboring cards keep aligned heights. |
| Complete personal context | Labels, focus outlines and searchable time-zone selection remain visible and keyboard accessible. |
| Save versus skip a step | Save persists the submitted values; skip preserves existing values and advances. |
| Change language halfway through a question | Workspace, start-step, question and fragment survive navigation. |
| Reload or use Back | Saved progress is restored in the correct account and organization. |
| Submit the initial welcome message | The visible default is actual editable content and appears in the live preview; clearing it deliberately remains possible. |
| Open optional deployment settings | Descriptions and links are visible without expanding a card. |
| Choose a monthly budget | Slider steps are whole USD, minimum 1; presets and no-limit work. Zero is never sent. |
| Keep an existing fractional budget unchanged | Continuing preserves its stored precision despite the whole-dollar display. |
| A save fails | The user stays in the current question and sees an actionable error; no completion is invented. |
| Finish while optional settings are empty | Completion is saved without requiring a model, invitation or successful AI run. |
| Close the start banner | It is hidden for 24 hours and returns only if onboarding remains unfinished and still applicable. |
| Keep the page open through snooze expiry, with a skewed computer clock | Expiry uses server time; no every-second retry loop occurs. |
| Switch account or workspace during a pending save | The delayed response updates only the initiating cache and cannot navigate the new account into the old workspace. |

## Invitations and mailbox proof

| Scenario | Expected result |
|---|---|
| Register someone else's invited email with a password | The invitation list is empty; accepting by guessed ID and reading the logo are refused. |
| Sign in through a fresh verified OAuth identity | Only invitations matching the email proved in this session become available. |
| Request and follow an email sign-in link | Only a link bound to the current address proves this session; legacy links still sign in but confer no mailbox proof. |
| Another password session exists for that same account | It does not inherit proof supplied by the mailbox owner in another session. |
| Refresh the proved session | Proof remains on that session row and is not copied to another session. |
| Change the account email | Old-address proof no longer unlocks invitations for the new address. |
| Follow the original invitation link | Token-based acceptance still works, including the staged sign-in round trip. |
| More than 100 invitations exist | Older invitations can be loaded using pagination; an individual logo is not restricted to the first page. |
| An invitation expires, is revoked, belongs to someone else, or is already accepted | No membership is created and the UI offers a retry instead of reporting success. |
| Dismiss the invitation dialog | An explicit shortcut remains; dismissal never accepts an invitation. |

## First conversation, Architect and maps

| Scenario | Expected result |
|---|---|
| AgenticOS is an accessible shipped draft without a key | It is selected for setup guidance; sending a message produces a progressively revealed setup reply and a model-connection card, without calling AI. |
| A member opens that setup chat | Guidance is available without granting model-management privileges. |
| No accessible shipped starter or published agent exists | The owner-help path remains available; no unrelated draft is treated as executable. |
| Open Architect in the widget and full chat | Both use the same setup reply and card behavior. |
| Load an older persisted setup reply | It keeps its agent identity and card; typing animation does not replay. |
| Reduced motion is enabled | Setup text and controls are available immediately. |
| Expand reasoning or tool details | Timeline connectors stay outside text and JSON in both themes. |
| Render a map without a tile configuration | Bundled SVG geography, markers and routes render without external tile requests. |
| Configure the optional street-map provider | Street detail is opt-in; a configured failing health probe remains visible. |
| Upgrade from released main or the existing onboarding preview head | Both histories reach `0302_merge_onboarding_chats.py` without replaying their column additions; alembic check reports no model drift. |

Automated coverage includes the invitation service and HTTP routes, mailbox proof,
session persistence on PostgreSQL, onboarding state, guided questions, locale navigation,
auth store, live chat events and persisted conversation conversion. The table also
contains manual acceptance paths; it does not claim every row was executed in a browser.
