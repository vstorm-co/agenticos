import { ROUTES } from "@/lib/constants";
import { AGENT_BUILDER, KB_DETAIL, ORG_MEMBERS, ORG_ROLES } from "@/lib/onboarding/tour";
import { Perm, type Permission } from "@/types/permissions";

/**
 * A guided *creation* flow — the Phase-2 counterpart to the passive tour.
 *
 * Where the tour (`tour.ts`) describes inert controls, a flow lets the reader
 * actually operate them: it points at the real control, the reader works the real
 * dialog, and the flow advances when the resource appears rather than when a Next
 * button is pressed. Most are one flow per resource a section can create; the id
 * is what the store carries in `"flow"` mode and what the "Create X?" offer names.
 * `explore-chat` is the exception — a guided run of the chat surface that creates
 * nothing, so its steps carry no signal and advance on Next.
 *
 * The passive tour and the flow are deliberately separate mechanisms, not one
 * with a flag: driver.js's overlay sits above the app and swallows clicks outside
 * its spotlight, so it would leave a create dialog dimmed and unusable. The coach
 * draws its own freeze instead — a dim with a cut-out over the one control — and
 * lifts it while a modal dialog or a picker is open, so the reader works it
 * against Radix's own stacking rather than a second one fighting it.
 */
export type FlowId =
  "create-agent" | "create-skill" | "create-kb" | "create-mcp" | "create-org" | "explore-chat";

/**
 * A resource whose *appearance* ends a step. It is the react-query list the coach
 * watches: when its count crosses the baseline captured as the step began, the
 * reader has created the thing and the step is done. The names track the hooks —
 * `mcp` is a connection in *either* scope (`useOrgMcpConnections` and the personal
 * `useMcpConnections`), because the flow teaches the connect mechanic, which is the
 * same whichever scope the reader picks; a walk that only counted org connections
 * hung when "Connect" defaulted to personal for a server the org already had. The
 * fork that branches on whether an agent has one to bind reads `hasOrgMcp`, which
 * stays org-only. `model` is a model profile (`useModelProviders`), the resource a
 * new agent needs before it can run.
 */
export type FlowResource = "agent" | "model" | "skill" | "kb" | "mcp" | "org";

/**
 * How a step knows it is finished. Five shapes.
 *
 * `created` is a resource appearing — the list the reader adds to grows by one.
 * The predicate is "count ≥ baseline + 1" and must be idempotent, because the
 * create hooks that patch the cache optimistically and then invalidate can tick
 * the count twice.
 *
 * `arrived` is the reader reaching a page — the signal for a step that teaches a
 * navigation rather than a creation, so the flow advances when the click it
 * pointed at lands rather than on a Next the reader could press without moving.
 * `page` is a page *identity* (`pageKey`), so `AGENT_BUILDER` matches whichever
 * `/agents/<id>` the reader opens. A step carrying one never auto-navigates —
 * the whole point is that the reader performs the move — so it names no `page`
 * of its own and points at the control that makes the move.
 *
 * `opened` is a modal dialog opening — the signal for a step that points at the
 * control which opens one, so the guidance moves into the dialog the moment the
 * reader does. It is settled by the coach rather than the hook (dialogs are
 * DOM), against the count of open dialogs when the step began, so a dialog
 * opened on top of another still reads as an opening.
 *
 * The remaining four read the agent this flow built (`flowAgentId`) or the chat
 * stores rather than a list count, carrying the run from a bare draft to a first
 * message sent — and each is a gate, not a Next the reader could press past.
 * `modelSet` is that agent's draft gaining a model, the one thing publish refuses
 * a spec without, so the walk cannot leave the model step model-less. `published`
 * is that agent gaining a published version — publish no-ops on an invalid spec,
 * so keying off the version keeps a broken or unpublished agent from ever
 * reaching the chat. `selected` is that agent being the one the chat will
 * address. `sent` is the reader sending their first message — the end of the
 * whole walkthrough, and the one place it asks for a (charged) model call,
 * because a first agent nobody has run is a tour that stopped one step short of
 * the point.
 */
export type FlowSignal =
  | { kind: "created"; resource: FlowResource }
  | { kind: "arrived"; page: string }
  | { kind: "opened" }
  | { kind: "modelSet" }
  | { kind: "published" }
  | { kind: "selected" }
  | { kind: "sent" };

/**
 * What an organization already has, read from the resource hooks, so an adaptive
 * flow can teach only what is missing, and ask to create what it lacks. A stored
 * key with no profile pointing at it is not a runnable model, and a profile whose
 * key was deleted is not either; a knowledge base, a skill or an MCP connection is
 * simply one the organization holds. `hasPublishedAgent` is the one the chat needs
 * — only a published agent has a version to run, so a draft does not count — which
 * is why the chat run asks to build one when there is none. A flow grows this as it
 * grows the branches that read it.
 */
export interface OrgState {
  hasRunnableModel: boolean;
  hasKnowledgeBase: boolean;
  hasSkill: boolean;
  hasOrgMcp: boolean;
  hasPublishedAgent: boolean;
}

/**
 * One stop in a creation flow.
 *
 * `page`/`target`/`activate`/`permission` mean what they do in `TourStep`: the
 * coach gets the reader to `page`, optionally reveals `activate`, and points at
 * `[data-tour="<target>"]`. What a flow step adds is `signal`, the app event that
 * advances it — a step with one auto-advances when its resource appears, a step
 * without one carries a Next (which is also how the reader moves past an optional
 * enrichment step without doing it). `include` makes a step adaptive: it runs
 * only when the organization's state calls for it, so a flow teaches "add a
 * model" only to an organization that has none.
 */
export interface FlowStep {
  id: string;
  page?: string;
  target?: string;
  /** A `[data-tour="…"]` to reveal before pointing at the target — a tab. */
  activate?: string;
  permission?: Permission;
  signal?: FlowSignal;
  /**
   * Run this step only when the organization's state calls for it. It is handed
   * `can` as well as the state, for the rare step that turns on a permission the
   * caller *lacks* — the model dead-end step, shown only to a builder who has no
   * model and cannot add one, where a `permission` field (which drops a step the
   * caller lacks) says the opposite of what is meant.
   */
  include?: (state: OrgState, can: (permission: Permission) => boolean) => boolean;
  /**
   * A fork rather than a control: the card asks a yes/no question instead of
   * pointing at anything, and the page freezes whole behind it. Answering `"yes"`
   * records the step's id and brings its detour — the steps that `requires` it —
   * into the flow; `"skip"` steps over them. Used where the flow can only go on
   * once the reader decides, as "no knowledge base yet — create one?" does.
   */
  question?: boolean;
  /**
   * A fork whose `"yes"` opens *another* flow rather than a detour within this
   * one. The chat run asks a reader with no published agent to build one first,
   * and yes hands off to `create-agent` whole — there is nothing to teach about
   * chat until an agent exists to address. `"skip"` still steps over it. Only a
   * `question` step reads this.
   */
  opensFlow?: FlowId;
  /**
   * Run this step only when the question with this id was answered `"yes"`. It is
   * the detour a fork opens: the guided creation and the round-trip back, present
   * only for a reader who asked for it.
   */
  requires?: string;
  /**
   * Resolve `target` against an id the coach captured at runtime rather than a
   * fixed `data-tour`. `"createdAgentEdit"` points at the edit control of the very
   * agent this flow created, so the return leg of a detour opens *that* agent's
   * builder — not the first card in a gallery that may hold many.
   */
  dynamicTarget?: "createdAgentEdit";
  /**
   * The target lives inside an open dialog. The freeze normally lifts whole
   * while one is open; a step marked so keeps guiding *into* it — the ring
   * renders over the dialog and frames the field the step is about, so the
   * walkthrough teaches what to put in each field rather than stopping at the
   * button that opened the form.
   */
  inOverlay?: boolean;
  /**
   * The reader chooses one of many, not a single named control — the server
   * catalog, where the step's whole point is that they pick whichever they want.
   * So the coach neither freezes nor rings: a spotlight on one card would both
   * hide the rest and contradict "find the one you want". It only shows the card
   * and waits for its signal (a connect dialog opening on whatever they picked).
   */
  roam?: boolean;
  /**
   * A control — by `data-tour` — the coach keeps click-blocked while this step
   * shows, lifted once the walk reaches the step that points at it. The create
   * dialogs enable their submit the moment a name is typed, so without this a
   * reader could submit from the first field and skip the walk through the rest;
   * the field steps name their dialog's submit here so it cannot be pressed until
   * the walk arrives on it. Leaves every other control, dropdowns included, live.
   */
  blockSubmit?: string;
  /**
   * Clear the open conversation on the way into this step, the way the builder's
   * own "Open in chat" does. Navigating to `/chat` with no `?id=` leaves whatever
   * thread was last selected selected — the chat loader only ever *sets* a
   * selection from the parameter, never clears one — so the first message the walk
   * asks for landed in an old thread, with its context and its agent.
   */
  freshConversation?: boolean;
}

/**
 * A named creation flow: its steps, and the permission that lets the caller
 * perform the creation at all. The offer is never shown to a caller lacking that
 * permission — pointing someone at a create button the server hid from them is a
 * 403 dressed as a tutorial. `permission` is omitted only where anyone may create
 * (an organization), and then the offer is always allowed.
 */
export interface CreationFlow {
  id: FlowId;
  permission?: Permission;
  steps: readonly FlowStep[];
}

/**
 * The flows.
 *
 * The per-section ones open at the section's create trigger — the reader is
 * already on the page when the "?" walk that offered it ends — then follow the
 * reader *into* the dialog, framing each field in turn with what to put in it,
 * and complete when the resource is created (the shared `*DialogSteps`
 * fragments, which the create-agent detours splice in too). `create-org` stays a
 * single step: its dialog is one name field, and walking that would be padding.
 * MCP carries a caveat neither the registry nor the coach can answer on its own: a
 * connection added over OAuth leaves the app for the provider's consent screen and
 * returns through a second full page load, so that path has no in-page `created`
 * signal to wait on and no store left to wait in. `OnboardingFlows` stows the
 * running flow across that round trip and puts it back on the way in.
 *
 * `create-agent` is the adaptive one. It creates the agent (which opens the
 * builder), walks its instructions and model, guides the knowledge, skills and MCP
 * servers it can be given, points out its tools, and publishes — then carries the
 * reader into the chat to pick the agent they just built and send it a first
 * message, ending only once that message is sent. The model
 * step is three mutually exclusive branches on what the organization and the
 * caller have: no runnable model and the permission to add one → taught to add it
 * inline (`AddModel` stores the key and the profile in a single submit); a model
 * already → only shown where to pick it; no model and no permission to add one →
 * told the organization has none and an admin must, rather than walked in silence
 * to a Publish that refuses a spec with no model.
 *
 * Knowledge and skills each branch the same way, on what the organization has.
 * With one already, the step just points at where it attaches and carries a Next.
 * With none, the step is a *fork*: "no knowledge base yet — create one?". Skip
 * moves on; Yes opens a detour that is the whole point of the guided flow — it
 * crosses into the Knowledge section, guides the creation, then walks the reader
 * *back*: click Agents in the sidebar, then the pencil on the agent just built,
 * then attach what was made. The return leg is taught, not driven — its steps
 * carry an `arrived` signal and no `page`, so the coach points at the control and
 * waits for the reader's click to land rather than navigating for them. The
 * pencil it points at is resolved from the id this flow captured (`dynamicTarget`),
 * so a gallery of many agents still returns to the right one.
 *
 * MCP forks the same way but stays put. The Toolbox binds a server with an inline
 * dialog rather than sending the reader to another page — the trip a knowledge base
 * or a skill has no choice but to make — so a reader with no connection is asked
 * and, on yes, pointed at that button; the connection it creates lands in the
 * picker's own cache and the step advances in place, no detour to walk and none to
 * return from.
 *
 * The steps from the builder on live on a detail view with no route of its own,
 * so they carry the `AGENT_BUILDER` identity and rely on an earlier step having
 * navigated there; the coach does not navigate to a pseudo-page.
 */
/**
 * The guided walk through one create dialog, field by field — shared between a
 * section's own flow and the create-agent detour into it, which is why each is
 * a function of `page` (the route the dialog opens over) and the fork whose
 * "yes" brought it in. The step ids are shared too, so the copy is written
 * once. Every step but the last advances on Next (typing has no signal); the
 * last points at the dialog's own Create and advances when the resource lands.
 */
function skillDialogSteps(page: string, requires?: string): FlowStep[] {
  return [
    {
      id: "flow-skill-field-name",
      page,
      target: "skill-dialog-name",
      permission: Perm.skillsEdit,
      inOverlay: true,
      blockSubmit: "skill-dialog-create",
      requires,
    },
    {
      id: "flow-skill-field-description",
      page,
      target: "skill-dialog-description",
      permission: Perm.skillsEdit,
      inOverlay: true,
      blockSubmit: "skill-dialog-create",
      requires,
    },
    {
      id: "flow-skill-field-source",
      page,
      target: "skill-dialog-editor",
      permission: Perm.skillsEdit,
      inOverlay: true,
      blockSubmit: "skill-dialog-create",
      requires,
    },
    {
      id: "flow-skill-field-create",
      page,
      target: "skill-dialog-create",
      permission: Perm.skillsEdit,
      inOverlay: true,
      signal: { kind: "created", resource: "skill" },
      requires,
    },
  ];
}

function kbDialogSteps(page: string, requires?: string): FlowStep[] {
  return [
    {
      id: "flow-kb-field-name",
      page,
      target: "kb-dialog-name",
      permission: Perm.collectionsEdit,
      inOverlay: true,
      blockSubmit: "kb-dialog-create",
      requires,
    },
    {
      id: "flow-kb-field-scope",
      page,
      target: "kb-dialog-scope",
      permission: Perm.collectionsEdit,
      inOverlay: true,
      blockSubmit: "kb-dialog-create",
      requires,
    },
    {
      id: "flow-kb-field-embeddings",
      page,
      target: "kb-dialog-embeddings",
      permission: Perm.collectionsEdit,
      inOverlay: true,
      blockSubmit: "kb-dialog-create",
      requires,
    },
    {
      id: "flow-kb-field-create",
      page,
      target: "kb-dialog-create",
      permission: Perm.collectionsEdit,
      inOverlay: true,
      signal: { kind: "created", resource: "kb" },
      requires,
    },
  ];
}

function mcpDialogSteps(page: string, requires?: string): FlowStep[] {
  return [
    {
      id: "flow-mcp-field-form",
      page,
      target: "mcp-dialog-form",
      permission: Perm.connectionsManage,
      inOverlay: true,
      blockSubmit: "mcp-dialog-connect",
      requires,
    },
    {
      id: "flow-mcp-field-connect",
      page,
      target: "mcp-dialog-connect",
      permission: Perm.connectionsManage,
      inOverlay: true,
      signal: { kind: "created", resource: "mcp" },
      requires,
    },
  ];
}

export const FLOWS: Record<FlowId, CreationFlow> = {
  "create-agent": {
    id: "create-agent",
    permission: Perm.agentsEdit,
    steps: [
      {
        id: "flow-agent-create",
        page: ROUTES.AGENTS,
        target: "agents-new",
        permission: Perm.agentsEdit,
        signal: { kind: "created", resource: "agent" },
      },
      {
        id: "flow-agent-instructions",
        page: AGENT_BUILDER,
        target: "agent-instructions",
        activate: "agent-tab-build",
        permission: Perm.agentsView,
      },
      {
        id: "flow-agent-model-add",
        page: AGENT_BUILDER,
        // The model *picker*, in the Build tab's Instructions card — not the
        // Model settings card (`agent-model`), which is temperature and thinking.
        target: "agent-model-picker",
        activate: "agent-tab-build",
        // Adding a model writes a `/providers/model-profiles`, which is
        // `connections:manage`, not `agents:view` — the same gate the picker's
        // "add" control carries. A caller with `agents:edit` but not that would
        // otherwise be walked to a control the server hides from them.
        permission: Perm.connectionsManage,
        // The *stored draft* gaining a model, not the profile list growing. Adding
        // a profile selects it on the builder's local spec, which is written back
        // behind a 1.2s debounce - and the step after this one crosses to Knowledge,
        // unmounting the builder and cancelling that save. Keyed off the list, the
        // walk advanced before the draft was ever stored, and the publish step it
        // walks to refuses a spec with no model, so the flow could not finish.
        signal: { kind: "modelSet" },
        include: (state) => !state.hasRunnableModel,
      },
      {
        id: "flow-agent-model-pick",
        page: AGENT_BUILDER,
        target: "agent-model-picker",
        activate: "agent-tab-build",
        // Selecting an existing model is part of editing the agent, which the
        // flow's own `agents:edit` gate already implies; it needs no
        // `connections:manage`.
        permission: Perm.agentsView,
        include: (state) => state.hasRunnableModel,
        // The step will not pass until a model is on the draft: an agent with none
        // cannot be published, so letting the reader skip here is the leak that
        // walks them to a Publish that refuses them.
        signal: { kind: "modelSet" },
      },
      // The dead end the other two leave: no runnable model, and no
      // `connections:manage` to add one. Neither add (dropped by permission) nor
      // pick (dropped by `include`) would show, and the reader would be walked in
      // silence to a Publish that refuses a spec with no model. This step breaks
      // that silence — it points at the picker, says the organization has no model
      // and an admin must add one, and carries a Next rather than a signal, because
      // there is nothing here this reader can create.
      {
        id: "flow-agent-model-none",
        page: AGENT_BUILDER,
        target: "agent-model-picker",
        activate: "agent-tab-build",
        permission: Perm.agentsView,
        include: (state, can) => !state.hasRunnableModel && !can(Perm.connectionsManage),
      },
      // Knowledge, with a knowledge base already: just show where it attaches.
      {
        id: "flow-agent-knowledge",
        page: AGENT_BUILDER,
        target: "capability-knowledge",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
        include: (state) => state.hasKnowledgeBase,
      },
      // Knowledge, with none: ask, and only to a caller who could create one —
      // pointing someone without `collections:edit` at a create they cannot do is
      // the 403-as-tutorial this gate exists to avoid, and there is nothing to
      // attach either, so the section drops for them entirely.
      {
        id: "flow-agent-knowledge-ask",
        // Ask on the Knowledge screen, not over the builder: the coach crosses to
        // it first so the question ("create one?") lands where the answer happens,
        // and a yes is already where the New button is.
        page: ROUTES.RAG,
        permission: Perm.collectionsEdit,
        include: (state) => !state.hasKnowledgeBase,
        question: true,
      },
      {
        id: "flow-agent-knowledge-create",
        page: ROUTES.RAG,
        target: "knowledge-new",
        permission: Perm.collectionsEdit,
        signal: { kind: "opened" },
        requires: "flow-agent-knowledge-ask",
      },
      ...kbDialogSteps(ROUTES.RAG, "flow-agent-knowledge-ask"),
      {
        id: "flow-agent-knowledge-return-nav",
        target: "nav-agents",
        permission: Perm.agentsView,
        signal: { kind: "arrived", page: ROUTES.AGENTS },
        requires: "flow-agent-knowledge-ask",
      },
      {
        id: "flow-agent-knowledge-return-edit",
        target: "agent-card-edit",
        dynamicTarget: "createdAgentEdit",
        permission: Perm.agentsEdit,
        signal: { kind: "arrived", page: AGENT_BUILDER },
        requires: "flow-agent-knowledge-ask",
      },
      {
        id: "flow-agent-knowledge-attach",
        page: AGENT_BUILDER,
        target: "capability-knowledge",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
        requires: "flow-agent-knowledge-ask",
      },
      // Skills, the same shape: attach an existing one, or ask and detour to make
      // one and bring it back.
      {
        id: "flow-agent-skills",
        page: AGENT_BUILDER,
        target: "capability-skills",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
        include: (state) => state.hasSkill,
      },
      {
        id: "flow-agent-skills-ask",
        // Same as knowledge: cross to the Skills screen, then ask there.
        page: ROUTES.SKILLS,
        permission: Perm.skillsEdit,
        include: (state) => !state.hasSkill,
        question: true,
      },
      {
        id: "flow-agent-skills-create",
        page: ROUTES.SKILLS,
        target: "skills-new",
        permission: Perm.skillsEdit,
        signal: { kind: "opened" },
        requires: "flow-agent-skills-ask",
      },
      ...skillDialogSteps(ROUTES.SKILLS, "flow-agent-skills-ask"),
      {
        id: "flow-agent-skills-return-nav",
        target: "nav-agents",
        permission: Perm.agentsView,
        signal: { kind: "arrived", page: ROUTES.AGENTS },
        requires: "flow-agent-skills-ask",
      },
      {
        id: "flow-agent-skills-return-edit",
        target: "agent-card-edit",
        dynamicTarget: "createdAgentEdit",
        permission: Perm.agentsEdit,
        signal: { kind: "arrived", page: AGENT_BUILDER },
        requires: "flow-agent-skills-ask",
      },
      {
        id: "flow-agent-skills-attach",
        page: AGENT_BUILDER,
        target: "capability-skills",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
        requires: "flow-agent-skills-ask",
      },
      {
        id: "flow-agent-tools",
        page: AGENT_BUILDER,
        target: "agent-capabilities",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
      },
      // MCP servers, the same fork as knowledge and skills, without the detour: the
      // Toolbox binds a server with an inline "Connect server" dialog, so a reader
      // who has one is only shown where it attaches, and one who has none is asked —
      // and on yes pointed at that button, gated on the `connections:manage` the
      // button itself carries. The connection lands in the picker's own cache and
      // the step advances in place, no trip to another page to make or return from.
      {
        id: "flow-agent-mcp",
        page: AGENT_BUILDER,
        target: "agent-mcp",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
        include: (state) => state.hasOrgMcp,
      },
      {
        id: "flow-agent-mcp-ask",
        // MCP connects inline in the Toolbox, so its "screen" is that tab: reveal
        // it, then ask there — the connect button the yes points at is right below.
        page: AGENT_BUILDER,
        activate: "agent-tab-toolbox",
        permission: Perm.connectionsManage,
        include: (state) => !state.hasOrgMcp,
        question: true,
      },
      {
        id: "flow-agent-mcp-connect",
        page: AGENT_BUILDER,
        target: "agent-mcp-connect",
        activate: "agent-tab-toolbox",
        permission: Perm.connectionsManage,
        signal: { kind: "opened" },
        requires: "flow-agent-mcp-ask",
      },
      // The builder's dialog holds the same catalog as the MCP page, so picking a
      // server opens the connect form as a second dialog — which the `opened`
      // signal reads as an opening because it counts dialogs, not just presence.
      {
        id: "flow-mcp-field-pick",
        page: AGENT_BUILDER,
        permission: Perm.connectionsManage,
        // Any of the catalog's servers, the reader's to choose — no spotlight on
        // one. Picking one opens the connect form as a second dialog, which the
        // `opened` signal reads as an opening because it counts dialogs.
        roam: true,
        signal: { kind: "opened" },
        requires: "flow-agent-mcp-ask",
      },
      ...mcpDialogSteps(AGENT_BUILDER, "flow-agent-mcp-ask"),
      // The connection exists, but nothing has given it to the agent: the builder
      // writes `spec.mcp_server_ids` only when the picker is toggled. So the detour
      // ends where the knowledge and skill ones do - back at the control that
      // attaches what was just made - rather than publishing an agent that cannot
      // reach the server the walk had the reader connect for it.
      {
        id: "flow-agent-mcp-attach",
        page: AGENT_BUILDER,
        target: "agent-mcp",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
        requires: "flow-agent-mcp-ask",
      },
      // Limits before Publish: a first agent that can run is a first agent that
      // can overspend, so the walk names the budget rather than leaving the tab
      // for the reader to find. Optional — a Next — because the defaults are safe.
      {
        id: "flow-agent-limits",
        page: AGENT_BUILDER,
        target: "agent-limits",
        activate: "agent-tab-limits",
        permission: Perm.agentsView,
      },
      {
        id: "flow-agent-publish",
        page: AGENT_BUILDER,
        target: "agent-publish",
        permission: Perm.agentsPublish,
        // Advance on the publish landing, not the click: publish refuses a spec
        // that fails validation (a missing model, most often), so keying off the
        // agent gaining a published version keeps a broken or unpublished agent
        // from ever reaching the chat steps that follow. Read per-agent from the
        // flow's own `flowAgentId`, which is captured past the create step so it
        // is the draft just built, never a published agent the flow passed through.
        signal: { kind: "published" },
      },
      // Building an agent is not the point; running it is. So the walk does not end
      // at Publish — it carries the reader into the chat, has them pick the agent
      // they just built, and ends only when they send it a first message. All three
      // steps are gated on `agents:publish`: a reader who could not publish has no
      // published agent to run, so the tail drops with the publish step rather than
      // walking them to a chat that cannot address one.
      {
        id: "flow-agent-run-pick",
        page: ROUTES.CHAT,
        target: "chat-agent-picker",
        permission: Perm.agentsPublish,
        signal: { kind: "selected" },
        freshConversation: true,
      },
      {
        id: "flow-agent-run-send",
        page: ROUTES.CHAT,
        target: "chat-composer",
        permission: Perm.agentsPublish,
        signal: { kind: "sent" },
      },
    ],
  },
  "create-skill": {
    id: "create-skill",
    permission: Perm.skillsEdit,
    steps: [
      {
        id: "flow-skill-create",
        page: ROUTES.SKILLS,
        target: "skills-new",
        permission: Perm.skillsEdit,
        signal: { kind: "opened" },
      },
      ...skillDialogSteps(ROUTES.SKILLS),
    ],
  },
  "create-kb": {
    id: "create-kb",
    permission: Perm.collectionsEdit,
    steps: [
      {
        id: "flow-kb-create",
        page: ROUTES.RAG,
        target: "knowledge-new",
        permission: Perm.collectionsEdit,
        signal: { kind: "opened" },
      },
      ...kbDialogSteps(ROUTES.RAG),
    ],
  },
  "create-mcp": {
    id: "create-mcp",
    permission: Perm.connectionsManage,
    steps: [
      // The catalog is on the page itself, so the walk opens by picking a server
      // — its Connect is what opens the connect form.
      {
        id: "flow-mcp-field-pick",
        page: ROUTES.MCP_SERVERS,
        permission: Perm.connectionsManage,
        // The catalog is the whole page here; the reader picks any server, and its
        // Connect opens the form. No spotlight — a hole over one card would lock
        // the choice the copy says is theirs to make.
        roam: true,
        signal: { kind: "opened" },
      },
      ...mcpDialogSteps(ROUTES.MCP_SERVERS),
    ],
  },
  "create-org": {
    id: "create-org",
    steps: [
      {
        id: "flow-org-create",
        page: ROUTES.ORGS,
        target: "orgs-new",
        signal: { kind: "created", resource: "org" },
      },
    ],
  },
  // A guided run of the chat surface, freezing it a control at a time to show how
  // a conversation is set up. The tour itself creates nothing — every step points,
  // explains, and advances on Next, because no resource's appearance could end it
  // and forcing the reader to send a (charged) message would teach the wrong
  // thing. It opens with one fork, though: the chat can only address a published
  // agent, so a reader with none is asked to build one first and yes hands off to
  // `create-agent`. That fork aside, anyone signed in can chat, so no step past it
  // carries a permission.
  "explore-chat": {
    id: "explore-chat",
    steps: [
      // The chat can only address a published agent, so a run with none to show
      // starts by asking to build one — and yes hands off to `create-agent` whole
      // (`opensFlow`) rather than touring an empty picker and a disabled composer.
      // Gated on the permission that create needs: a reader who cannot build an
      // agent is not offered the flow they could not run, and simply gets the
      // descriptive tour. Skip takes anyone straight into it.
      {
        id: "flow-chat-needs-agent",
        page: ROUTES.CHAT,
        permission: Perm.agentsEdit,
        // Publish as well as edit, through `include` because a step carries one
        // `permission`. `create-agent`'s publish step and the whole chat tail after
        // it are gated on `agents:publish`, which the built-in Member role does not
        // hold - so a Member accepting this hand-off built a draft, lost the tail to
        // the filter, and never returned to the chat walk the fork exists to unblock.
        // Without publish they get the descriptive tour instead, which works.
        include: (state, can) => !state.hasPublishedAgent && can(Perm.agentsPublish),
        question: true,
        opensFlow: "create-agent",
      },
      { id: "flow-chat-start", page: ROUTES.CHAT, target: "chat-start" },
      { id: "flow-chat-agent", page: ROUTES.CHAT, target: "chat-agent-picker" },
      { id: "flow-chat-controls", page: ROUTES.CHAT, target: "chat-model-picker" },
      { id: "flow-chat-composer", page: ROUTES.CHAT, target: "chat-composer" },
    ],
  },
};

/**
 * The flow offered at the end of a section's "?" walk, or `null` for a page with
 * nothing to offer. Detail routes collapse onto their section the way `pageKey`
 * collapses them, so the builder offers the same flow as the Agents list and a
 * collection the same as the Knowledge list — which is why an Agents "?" that
 * walked into the builder still offers `create-agent`. Chat is the odd one: it
 * creates nothing, but its walk offers `explore-chat`, the guided run of the
 * surface itself.
 */
export function flowForPage(pageId: string): FlowId | null {
  switch (pageId) {
    case ROUTES.CHAT:
      return "explore-chat";
    case ROUTES.AGENTS:
    case AGENT_BUILDER:
      return "create-agent";
    case ROUTES.SKILLS:
      return "create-skill";
    case ROUTES.RAG:
    case KB_DETAIL:
      return "create-kb";
    case ROUTES.MCP_SERVERS:
      return "create-mcp";
    case ROUTES.ORGS:
    case ORG_MEMBERS:
    case ORG_ROLES:
      return "create-org";
    default:
      return null;
  }
}

/**
 * The steps of `flow` this caller runs against `state` and the forks they have
 * answered in `choices`.
 *
 * Three filters, all in the dropping direction. Permission-filtered the way the
 * tour is — a step whose control the server would hide is dropped rather than
 * left for the coach to hunt. Adaptively filtered on `state` (and `can`, which the
 * predicate is handed for the one step that turns on a permission the caller
 * *lacks*), so a step that only makes sense for a missing prerequisite (add a
 * model, ask about a knowledge base) drops out for an organization that already
 * has it, and its complement (pick the model, attach the base) takes its place.
 * And fork-filtered on
 * `choices`, so a detour step runs only once its question was answered `"yes"` —
 * which is what lets recording an answer widen the step list, the question
 * sitting immediately before the steps it gates so the index after it lands on
 * the first of them. The flow-level permission gates whether the offer is made at
 * all; this gates the steps within one that is.
 */
export function stepsForFlow(
  flow: CreationFlow,
  state: OrgState,
  can: (permission: Permission) => boolean,
  choices: Record<string, "yes" | "skip">,
): readonly FlowStep[] {
  return flow.steps.filter(
    (step) =>
      (!step.permission || can(step.permission)) &&
      (!step.include || step.include(state, can)) &&
      (!step.requires || choices[step.requires] === "yes"),
  );
}

/**
 * Whether a caller may be offered `flow` — they hold the permission it needs, or
 * it needs none. Used to decide if the "Create X?" prompt is shown.
 */
export function canOfferFlow(
  flow: CreationFlow,
  can: (permission: Permission) => boolean,
): boolean {
  return !flow.permission || can(flow.permission);
}
