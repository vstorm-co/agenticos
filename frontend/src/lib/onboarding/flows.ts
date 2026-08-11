import { ROUTES } from "@/lib/constants";
import { AGENT_BUILDER, KB_DETAIL, ORG_MEMBERS, ORG_ROLES } from "@/lib/onboarding/tour";
import { Perm, type Permission } from "@/types/permissions";

/**
 * A guided *creation* flow — the Phase-2 counterpart to the passive tour.
 *
 * Where the tour (`tour.ts`) describes inert controls, a flow lets the reader
 * actually make the thing: it points at the real create control, the reader
 * operates the real dialog, and the flow advances when the resource appears
 * rather than when a Next button is pressed. One flow per resource a section can
 * create; the id is what the store carries in `"flow"` mode and what the "Create
 * X?" offer names.
 *
 * The passive tour and the flow are deliberately separate mechanisms, not one
 * with a flag: driver.js's overlay sits above the app and swallows clicks outside
 * its spotlight, so it would leave a create dialog dimmed and unusable. The coach
 * that runs a flow draws no blocking overlay for exactly that reason.
 */
export type FlowId = "create-agent" | "create-skill" | "create-kb" | "create-mcp" | "create-org";

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
 * How a step knows it is finished. Today the only signal is a resource being
 * created — the list the reader adds to grows by one. The predicate is
 * "count ≥ baseline + 1" and must be idempotent, because the create hooks that
 * patch the cache optimistically and then invalidate can tick the count twice.
 */
export type FlowSignal = { kind: "created"; resource: FlowResource };

/**
 * What an organization already has, read from the resource hooks, so an adaptive
 * flow can teach only what is missing. Just `hasRunnableModel` today — the one
 * prerequisite a new agent cannot run without — because a stored key with no
 * profile pointing at it is not runnable, and a profile whose key was deleted is
 * not either. A flow grows this as it grows the branches that read it.
 */
export interface OrgState {
  hasRunnableModel: boolean;
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
  /** Run this step only when the organization's state calls for it. */
  include?: (state: OrgState) => boolean;
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
 * builder), walks its instructions and model, points out the knowledge, skills
 * and tools it can be given, and ends at Publish. The model step is two mutually
 * exclusive halves: an organization with no runnable model is taught to add one
 * inline (`AddModel` stores the key and the profile in a single submit), one that
 * already has a model is only shown where to pick it. The knowledge/skills/tools
 * steps carry no signal — they are "attach one, or move on with Next", because a
 * first agent needs none of them; a reader who wants to create one has each
 * section's own "?" flow. Its later steps live on the builder, a detail view with
 * no route of its own, so they carry the `AGENT_BUILDER` identity and rely on the
 * create step having navigated there; the coach does not navigate to a pseudo-page.
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
      {
        id: "flow-agent-knowledge",
        page: AGENT_BUILDER,
        target: "agent-collections",
        activate: "agent-tab-knowledge",
        permission: Perm.agentsView,
      },
      {
        id: "flow-agent-skills",
        page: AGENT_BUILDER,
        target: "agent-skills",
        activate: "agent-tab-skills",
        permission: Perm.agentsView,
      },
      {
        id: "flow-agent-tools",
        page: AGENT_BUILDER,
        target: "agent-capabilities",
        activate: "agent-tab-toolbox",
        permission: Perm.agentsView,
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
};

/**
 * The flow offered at the end of a section's "?" walk, or `null` for a page with
 * nothing to create. Detail routes collapse onto their section the way `pageKey`
 * collapses them, so the builder offers the same flow as the Agents list and a
 * collection the same as the Knowledge list — which is why an Agents "?" that
 * walked into the builder still offers `create-agent`.
 */
export function flowForPage(pageId: string): FlowId | null {
  switch (pageId) {
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
 * The steps of `flow` this caller runs against `state`: permission-filtered the
 * way the tour is — a step whose control the server would hide is dropped rather
 * than left for the coach to hunt — and adaptively filtered, so a step that only
 * makes sense for a missing prerequisite (add a model) drops out for an
 * organization that already has it, and its complement (pick the model you have)
 * takes its place. The flow-level permission gates whether the offer is made at
 * all; this gates the steps within one that is.
 */
export function stepsForFlow(
  flow: CreationFlow,
  state: OrgState,
  can: (permission: Permission) => boolean,
): readonly FlowStep[] {
  return flow.steps.filter(
    (step) => (!step.permission || can(step.permission)) && (!step.include || step.include(state)),
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
