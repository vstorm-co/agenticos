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
 * `orgMcp` is the organization's MCP connections (`useOrgMcpConnections`), not the
 * personal `/me` list and not the read-only catalog; `model` is a model profile
 * (`useModelProviders`), the resource a new agent needs before it can run.
 */
export type FlowResource = "agent" | "model" | "skill" | "kb" | "orgMcp" | "org";

/**
 * How a step knows it is finished. Two shapes.
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
 */
export type FlowSignal =
  { kind: "created"; resource: FlowResource } | { kind: "arrived"; page: string };

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
 * The per-section ones are a single step pointing at the section's create trigger
 * — the reader is already on the page when the "?" walk that offered it ends — and
 * complete when the resource is created. MCP carries a caveat the coach handles,
 * not the registry: a connection added over OAuth redirects to the provider's
 * consent screen rather than resolving in place, so that path has no in-page
 * `created` signal to wait on.
 *
 * `create-agent` is the adaptive one. It creates the agent (which opens the
 * builder), walks its instructions and model, guides the knowledge, skills and MCP
 * servers it can be given, points out its tools, and ends at Publish. The model
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
        signal: { kind: "created", resource: "model" },
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
        target: "agent-collections",
        activate: "agent-tab-knowledge",
        permission: Perm.agentsView,
        include: (state) => state.hasKnowledgeBase,
      },
      // Knowledge, with none: ask, and only to a caller who could create one —
      // pointing someone without `collections:edit` at a create they cannot do is
      // the 403-as-tutorial this gate exists to avoid, and there is nothing to
      // attach either, so the section drops for them entirely.
      {
        id: "flow-agent-knowledge-ask",
        permission: Perm.collectionsEdit,
        include: (state) => !state.hasKnowledgeBase,
        question: true,
      },
      {
        id: "flow-agent-knowledge-create",
        page: ROUTES.RAG,
        target: "knowledge-new",
        permission: Perm.collectionsEdit,
        signal: { kind: "created", resource: "kb" },
        requires: "flow-agent-knowledge-ask",
      },
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
        target: "agent-collections",
        activate: "agent-tab-knowledge",
        permission: Perm.agentsView,
        requires: "flow-agent-knowledge-ask",
      },
      // Skills, the same shape: attach an existing one, or ask and detour to make
      // one and bring it back.
      {
        id: "flow-agent-skills",
        page: AGENT_BUILDER,
        target: "agent-skills",
        activate: "agent-tab-skills",
        permission: Perm.agentsView,
        include: (state) => state.hasSkill,
      },
      {
        id: "flow-agent-skills-ask",
        permission: Perm.skillsEdit,
        include: (state) => !state.hasSkill,
        question: true,
      },
      {
        id: "flow-agent-skills-create",
        page: ROUTES.SKILLS,
        target: "skills-new",
        permission: Perm.skillsEdit,
        signal: { kind: "created", resource: "skill" },
        requires: "flow-agent-skills-ask",
      },
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
        target: "agent-skills",
        activate: "agent-tab-skills",
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
        signal: { kind: "created", resource: "orgMcp" },
        requires: "flow-agent-mcp-ask",
      },
      {
        id: "flow-agent-publish",
        page: AGENT_BUILDER,
        target: "agent-publish",
        permission: Perm.agentsPublish,
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
        signal: { kind: "created", resource: "skill" },
      },
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
        signal: { kind: "created", resource: "kb" },
      },
    ],
  },
  "create-mcp": {
    id: "create-mcp",
    permission: Perm.connectionsManage,
    steps: [
      {
        id: "flow-mcp-create",
        page: ROUTES.MCP_SERVERS,
        target: "mcp-add",
        permission: Perm.connectionsManage,
        signal: { kind: "created", resource: "orgMcp" },
      },
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
        include: (state) => !state.hasPublishedAgent,
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
