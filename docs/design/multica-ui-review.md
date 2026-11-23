# Multica UI review and AgenticOS adoption plan

Reviewed 22 November 2026. This report records the design evidence, the focused changes in PR #3137 and the wider follow-ups. It does not claim that every console screen has been redesigned.

## Scope and evidence

Multica was inspected at commit [`7720f0d597a29da5d2eb767225916a30e7b5af1f`](https://github.com/multica-ai/multica/tree/7720f0d597a29da5d2eb767225916a30e7b5af1f). The review covers its [issue](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/docs/assets/readme/issue.webp), [agent/team](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/docs/assets/readme/team.webp) and [run](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/docs/assets/readme/run.webp) screenshots, the public [product page](https://multica.ai/), and the source paths linked below. No authenticated Multica session was used. Screenshots demonstrate selected states, not every interaction or current production configuration.

The analysis borrows interaction principles, not implementation. No Multica code or assets are copied into AgenticOS. Multica's [license](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/LICENSE) includes conditions beyond the Apache text; this review does not treat it as an unrestricted component library.

## Why its application feels clean

The strongest distinction is the allocation of attention. Content, navigation, properties and commands have separate places. Small decisions do not each receive their own large card, illustration and explanation.

| Observed pattern | Evidence | What AgenticOS should adopt |
| --- | --- | --- |
| A stable list → detail → properties relationship | Issue and team screenshots keep the work in the central pane and metadata in the inspector. A selected row is restrained rather than another large surface. | Preserve list context while inspecting an agent or run; make the main pane about the work and put secondary metadata in a consistent inspector. |
| Work before configuration | The team screenshot puts the current run and recent work above the properties column. Status, model and runtime are compact facts. | Let an agent's overview answer what it is doing, what it produced and what needs attention before presenting its full spec. |
| A small type hierarchy | [Type roles, `tokens.css:70–129`](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/ui/styles/tokens.css#L70-L129) distinguish body, metadata, helper text and titles, with a paired line height. | Define a small set of console text roles; migrate inconsistent local values progressively. Keep marketing display typography out of dense work screens. |
| Surface roles rather than a card around everything | The screenshots use whitespace and hairlines for ordinary structure, cards for selected activity and interactive objects. [Radius roles](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/ui/styles/tokens.css#L57-L67) distinguish controls from surfaces. | Remove redundant outer cards and repeated section borders while preserving real interactive boundaries. |
| One compact location header | [BreadcrumbHeader](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/views/layout/breadcrumb-header.tsx#L38-L69) shares one containment model and action slot across detail pages. | Use the existing AgenticOS PageHeader consistently; avoid repeating the same resource name in a breadcrumb, oversized title and card header. |
| Motion belongs to a specific event | [The right inspector](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/views/layout/animated-right-sidebar.tsx#L22-L35) defines its transition separately from resizing; [base.css](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/ui/styles/base.css#L369-L380) animates explicit toggles, not every layout restoration. | Give opening, selection and navigation a consistent response; do not animate initial saved-layout restoration or user-controlled resizing. |

AgenticOS already has much of the foundation: neutral selected navigation in `app-sidebar.tsx`, permission-filtered groups in `nav-sections.ts`, descriptions moved into contextual help by `dashboard/page-header.tsx`, and shared motion values in `globals.css`. The proposal is to complete that consistency. A new font, global palette or third sidebar is not required to obtain the useful part of Multica's presentation.

## Onboarding: evidence and its limits

Multica's source uses a [28rem form column and one title/supporting line](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/views/onboarding/components/step-shell.tsx#L19-L49). Its [persisted path](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/core/onboarding/step-order.ts#L3-L13) is about-you → workspace → runtime. A connected runtime leads to a real Mika conversation; skipping it has a separate guide destination, according to the [flow contract](https://github.com/multica-ai/multica/blob/7720f0d597a29da5d2eb767225916a30e7b5af1f/packages/views/onboarding/onboarding-flow.tsx#L94-L98). This is more useful than reproducing its exact screen count: AgenticOS has different model, credential and MCP contracts.

The large-product references point to a similar direction:

| Primary source | Observed approach | AgenticOS application |
| --- | --- | --- |
| [Linear Start Guide](https://linear.app/docs/start-guide) and [workspace documentation](https://linear.app/docs/workspaces) | Concrete workspace examples, separate guidance for administrators and members, and role-dependent settings. | Put the first useful task ahead of deployment policy; show only settings the person owns. |
| Slack's [new-member guide](https://slack.com/help/articles/218080037-Getting-started-for-new-Slack-users) and [workspace-creator guide](https://slack.com/help/articles/217626298-Getting-started-for-workspace-creators) | Members learn profile, preferences and messaging; creators get workspace/channel/team setup. | Keep personal setup separate from invitation and deployment configuration. A member should not have to understand an administrator's choices to start. |
| [Notion's first-page guide](https://www.notion.com/help/create-your-first-page) | Start writing in the real object; import, templates and commands appear in that context. | Start in a real AgenticOS chat or Architect draft. Offer relevant additions once a task makes their purpose clear. |
| [Intercom's signup retrospective](https://www.intercom.com/blog/yesterdays-signup-wont-work-today/) | People signing up may lack the data, authority or technical ability to finish setup; the flow allows exploration and teammate help. | Make missing organization credentials a clear handoff, not a dead end. Personal subscriptions can provide an independent path where the agent supports them. |
| [Intercom Customer Milestones](https://www.intercom.com/blog/customer-milestones-framework) | Setup, activation, utilization and maturity are distinct milestones; the team validates relationships with meaningful usage. | Wizard completion is not evidence that someone received useful agent output. Measure those outcomes separately. |

These are documented patterns and vendor accounts, not proof that a particular AgenticOS animation or step count will improve retention. Their public documentation is not a complete recording of every current signup screen. Any retention claim needs evidence from our own users.

## Studio contract

The chosen direction is a quiet Studio with a small navigation rail and one main task. Keep the existing console language and leave playful character motion to deliberate moments.

1. **Workspace:** choose or create the destination. Present its name once. Do not add a second organization preview or a second explanation below the first. A unique existing destination may be preselected, while the user retains a way to change it.
2. **Personal identity:** ask for the name/profile information that will actually be used. The blob carousel is the interaction here, not an illustration repeated in the rail. A saved photo remains supported.
3. **Useful context:** optional, short prompts for what the agents should know. Explain who can use this context and preserve the existing account scope. Skip is explicit.
4. **Model connection:** present existing workspace models and Vault keys, personal subscriptions and a new API-key path. Distinguish connected, usable and selected; one does not imply the others. Preserve each selected account's own catalog and quota state.
5. **Tools:** offer relevant MCP services plus the custom-server path. State the difference between connecting an account and authorizing an agent to use it. Search and pagination remain available without turning the wizard into a full catalogue tour.
6. **First task:** show the installed AgenticOS and Architect with distinct roles and an actual destination. Opening them prepares the working surface; it does not automatically submit a prompt or spend tokens.
7. **Administrative follow-up:** invitations, registration policy, budgets and deployment settings remain reachable, but need not block first use. Required deployment constraints still apply; skipping a screen must not silently change policy.

This is a sequence of user decisions, not a requirement to force seven full-screen forms. Small adjacent questions can share a step if they remain easy to understand. The rail must accurately identify the current section, avoid completion checkmarks for unsaved or skipped settings, and preserve drafts when revisiting mounted steps.

Remove the Studio variant switcher from ordinary first use. Keep preview URLs for design review. Do not show the same blob beside the sidebar introduction, the guide name, a promotional card and the form. One active character is sufficient; AgenticOS and Architect can both appear when the user is choosing between them.

## Motion and personality

Use the existing `--duration-fast`, `--duration-panel`, `--duration-base` and `--duration-slow` values rather than adding another timing system. This fits [Atlassian's motion guidance](https://atlassian.design/foundations/motion): brief feedback for frequent interactions, a single focal event, and more expression reserved for occasional moments.

| Event | Proposed response | Constraint |
| --- | --- | --- |
| Continue / Back | Short directional content transition; focus the incoming heading. | Controls work immediately; no wait for animation completion. Keep the footer and rail in place. |
| Blob browsing | Native horizontal scrolling with snap positions, pointer/touch gestures and named previous/next controls; emphasize the chosen option. | Browsing must not silently save every crossed option. Preserve the real avatar-color contract. |
| Blob selection | A brief settle/scale response and visible selected outline. | Show saving/failure truthfully. Use text/shape as well as color to communicate selection. |
| Successful connection | Replace the connect control with the account identity and a restrained status transition. | No repeated success toast; a failed connection retains its retry action. |
| Optional section | A short disclosure transition while keeping its trigger in place. | Expanded state and keyboard focus remain stable. |
| First-agent introduction | One brief character entrance or settling motion. | No continuous bouncing beside the task; no artificial claim that an agent is working. |

Do not type long mandatory instructions character by character. A short optional guide can reveal text, but its full content must remain accessible and the form must stay usable. Avoid looping decoration in the navigation. Test both the operating-system reduced-motion preference and the application's own setting.

[W3C's carousel guidance](https://www.w3.org/WAI/tutorials/carousels/) requires keyboard operation, understandable focus and communicated item changes. Prefer a user-controlled avatar picker with no autoplay. If persistent autoplay is later introduced, it also needs a visible pause control; reduced motion alone is not a replacement for that control.

## Changes implemented in PR #3137

The user selected Studio and then requested the same principles across everyday console work. The implementation extends the existing design system and data contracts:

- Studio has one principal form column, a quiet phase rail and no top-right step counter. Optional administrator settings can follow the first useful task. Conversation and Launchpad remain explicit preview variants.
- Models use the real catalog and existing Vault credentials; subscriptions connect directly from recognizable provider tiles. MCP setup uses the existing connection flow and retains the distinction between a connected account and tools assigned to an agent.
- A draggable spring gallery browses the actual account palette. Swiping and keyboard navigation do not save; choosing a look uses the existing profile update. Uploaded photos remain the primary identity.
- Shared page and section titles use consistent text roles. Lists wrap their controls on narrow screens. An embedded table shares its list's boundary instead of adding a second outer frame; its loading rows retain their configured height.
- Settings section icons no longer need a decorative tile for ordinary structure. Destructive sections retain their existing emphasis.
- Primary sidebar destinations and recent projects now share one row geometry, neutral selection, text weight and keyboard focus outline. Search, collapse and New chat use the navigation's existing 18px/1.75-stroke icon treatment. The collapsed rail keeps an accessible icon-only New chat shortcut; the expanded sidebar and phone drawer retain its label and dismissal behavior. These changes reuse the current font and color tokens.

- Agent cards open Build while keeping their evaluation-attention indicator. Recent runs remain in Activity with existing agent filters; the trial Recent work panel above Builder was removed after visual review. Explicit configuration and evaluation deep links remain available.
- The run inspector exposes the recorded failure reason before events. Standalone transcripts use independent chronological disclosures, readable text and complete raw JSON on demand; unknown structured events retain a raw view.
- The chat model control shows the model above its provider or the selected personal account's email/label, without internal routing IDs. Projects precede Build. Knowledge starts folded, while its active page and the person's explicit expansion remain available.

The design opportunities in the next table are a roadmap; a shared-component improvement does not mean every local screen has been migrated. A unified list-detail inspector for all resources, a console-wide empty-state audit and activation measurement remain follow-ups.

## Wider console opportunities

P0 covers first-use clarity; P1 and P2 describe priorities across the console. Some are addressed by the changes above, while broader inspection and state consistency still need focused follow-ups.

| Priority | Concrete change | Existing implementation to extend | Review criterion |
| --- | --- | --- | --- |
| P0 | Simplify Studio's heading, guide, rail and preview hierarchy. | `components/onboarding/start-experience.tsx`, `start-guide.tsx`, `start-workspace*.tsx`. | At each stage there is one principal question, one supporting explanation and one primary action. |
| P0 | Make connected / usable / selected model states distinct, including an empty organization. | `chat/chat-model-library.tsx`, `agents/subscription-model-form.tsx`, `onboarding/start-connections.tsx`. | A new user can identify the current model, its account and the next action without understanding gateway terminology. |
| P0 | End onboarding in real AgenticOS / Architect work and retain missing-model guidance. | `onboarding/start-launch.tsx`, existing chat setup path. | A link opens the actual authorized agent; setup completion never claims an AI result. |
| P1 | Standardize text roles and line heights for lists, properties, helper text and headings. | `app/globals.css`, `dashboard/page-header.tsx`, shared UI components. | The same role has the same treatment in Agents, Vault, MCP and Runs; support text scaling and 200% zoom. |
| P1 | Apply a clear surface hierarchy: page, optional inspector, interactive card. Remove nested cards used only for spacing. | `ui/list-card.tsx`, settings `SectionCard`, Builder sections. | Each visible border indicates a meaningful grouping or interaction, and dense lists need fewer enclosing rectangles. |
| P1 | Make agent overviews show current work, recent results and attention before full configuration. | Agent detail/overview components and existing run hooks. | A returning user can find the latest result or failure without opening the Builder. Preserve permission-specific visibility. |
| P1 | Converge list-detail inspection across Agents, Runs and relevant resources. | `runs/run-detail-panel.tsx`, existing resizable panel hook and page headers. | Opening a detail preserves filters, selection, scroll and Back behavior; mobile uses one pane with a clear return path. |
| P1 | Refine the run inspector into summary → chronological events → selected event detail. Keep raw payloads secondary. | `runs/focused-run.tsx`, `run-timeline.tsx`, `run-waterfall.tsx`, `run-manifest.tsx`. | A failed run answers what failed, what it affected and what can be retried before showing raw JSON. Existing inspection features remain available. |
| P1 | Give list toolbars one consistent order: search, optional filters, primary create action, count. | `ui/list-card.tsx`, `ui/data-table.tsx`, shared search/filter components. | Filter/search/page state survives inspection; loading geometry and keyboard focus do not jump. |
| P1 | Use one account-row language for subscription accounts and API credentials. Show quota windows beside the actual account. | `settings/subscription-accounts.tsx`, `agents/subscription-account-usage.tsx`, Vault provider rows. | Multiple accounts remain distinguishable; unavailable quota is not rendered as zero or an empty progress bar. |
| P1 | Reduce composer chrome and keep selected model/account identity legible. Secondary capability tuning stays behind Tools & files. | `chat/chat-layout.tsx`, `chat-layout.css`, model picker header. | On phone widths the model name, send action and account switch remain reachable without collisions or unexplained truncated account IDs. |
| P2 | Refine navigation around daily work and configuration frequency, using existing collapsible sections. | `lib/nav-sections.ts`, `layout/app-sidebar.tsx`, shared command/search registry. | Common work remains one click away; rare configuration does not crowd the first viewport; no destination disappears from mobile or command search. |
| P2 | Create a shared inspector/disclosure motion contract with immediate restoration and reduced-motion behavior. | Existing motion tokens, resizable panels and disclosure primitives. | Toggling animates once; resizing and restoring a saved layout remain responsive and stable. |
| P2 | Give blank states a concrete next task instead of another feature description. | Existing `EmptyState` consumers and dashboard setup guidance. | Each state distinguishes no data, no permission, failed read and incomplete setup, with one relevant action. |

Do not replace every table with tiles, introduce a second icon vocabulary, or shrink all controls to screenshot density. Connections benefit from recognizable logos; long work histories benefit from rows. Touch controls, forced colors, keyboard navigation and error recovery are part of the same design review.

## Validation and retention questions

First validate the working flow with new members and administrators separately: can they choose a model, connect an account, understand which tools an agent may use, and start a real task without assistance? Include a workspace with existing Vault keys, no shared model, several subscription accounts, failed quota reads and a member who cannot edit organization settings.

Then define a meaningful activation outcome for each path. Examples are a useful completed AgenticOS task, an Architect draft the person chooses to review, or a connected tool successfully used in an authorized task. A connected account or the last wizard button alone is insufficient.

Potential measures are time to first useful outcome, step abandonment and recovery, setup failures, return to a second meaningful task, and later repeated usage. These are proposals for an explicit measurement design, not new tracking implemented by this review. Compare cohorts and distinguish correlation from causation before claiming improved retention.

Before shipping a visual follow-up, compare desktop and 390px layouts, light/dark themes, long localized labels, keyboard-only operation, reduced motion, loading geometry, failed reads and restored navigation. Static screenshots are necessary for hierarchy; a complete interactive pass is necessary for behavior.
