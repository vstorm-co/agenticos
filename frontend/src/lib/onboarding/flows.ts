import { ROUTES } from "@/lib/constants";
import { KB_DETAIL, ORG_MEMBERS, ORG_ROLES } from "@/lib/onboarding/tour";
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
export type FlowId = "create-skill" | "create-kb" | "create-mcp" | "create-org";

/**
 * A resource whose *appearance* ends a step. It is the react-query list the coach
 * watches: when its count crosses the baseline captured as the step began, the
 * reader has created the thing and the step is done. The names track the hooks —
 * `orgMcp` is the organization's MCP connections (`useOrgMcpConnections`), not the
 * personal `/me` list and not the read-only catalog.
 */
export type FlowResource = "skill" | "kb" | "orgMcp" | "org";

/**
 * How a step knows it is finished. Today the only signal is a resource being
 * created — the list the reader adds to grows by one. The predicate is
 * "count ≥ baseline + 1" and must be idempotent, because the create hooks that
 * patch the cache optimistically and then invalidate can tick the count twice.
 */
export type FlowSignal = { kind: "created"; resource: FlowResource };

/**
 * One stop in a creation flow.
 *
 * `page`/`target`/`activate`/`permission` mean what they do in `TourStep`: the
 * coach gets the reader to `page`, optionally reveals `activate`, and points at
 * `[data-tour="<target>"]`. What a flow step adds is `interactive` — the coach
 * enables pointer events on the target and does *not* perform the action itself,
 * so the reader operates the real control — and `signal`, the app event that
 * advances the step. `optional` renders a Skip.
 */
export interface FlowStep {
  id: string;
  page?: string;
  target?: string;
  /** A `[data-tour="…"]` to reveal before pointing at the target — a tab. */
  activate?: string;
  permission?: Permission;
  /** The reader acts on the real control; the coach waits rather than clicking. */
  interactive?: boolean;
  /** Renders a Skip — a step the flow can do without. */
  optional?: boolean;
  signal?: FlowSignal;
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
 * The per-section flows. Each is a single interactive step pointing at the
 * section's create trigger — the reader is already on the page when the "?" walk
 * that offered it ends — and completes when the resource is created.
 *
 * MCP is the one with a caveat the coach carries, not the registry: a connection
 * added over OAuth redirects to the provider's consent screen instead of
 * resolving in place, so that path has no in-page `created` signal to wait on.
 */
export const FLOWS: Record<FlowId, CreationFlow> = {
  "create-skill": {
    id: "create-skill",
    permission: Perm.skillsEdit,
    steps: [
      {
        id: "flow-skill-create",
        page: ROUTES.SKILLS,
        target: "skills-new",
        permission: Perm.skillsEdit,
        interactive: true,
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
        interactive: true,
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
        interactive: true,
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
        interactive: true,
        signal: { kind: "created", resource: "org" },
      },
    ],
  },
};

/**
 * The flow offered at the end of a section's "?" walk, or `null` for a page with
 * nothing to create. Detail routes collapse onto their section the way `pageKey`
 * collapses them, so the builder offers the same flow as the Agents list and a
 * collection the same as the Knowledge list.
 *
 * Agents has no entry yet — its guided flow (adaptive, multi-step, ending in a
 * publish) is added with the flow itself; until then the Agents "?" ends without
 * an offer rather than with a broken one.
 */
export function flowForPage(pageId: string): FlowId | null {
  switch (pageId) {
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
 * The steps of `flow` this caller can run, permission-filtered the way the tour
 * is: a step whose control the server would hide is dropped rather than left for
 * the coach to hunt. The flow-level permission gates whether the offer is made at
 * all; this gates the steps within one that is.
 */
export function stepsForFlow(
  flow: CreationFlow,
  can: (permission: Permission) => boolean,
): readonly FlowStep[] {
  return flow.steps.filter((step) => !step.permission || can(step.permission));
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
