/** What the console hears when a resource changes somewhere else (#2061). */

export type ChangeResource =
  | "agent"
  | "skill"
  | "context"
  | "knowledge_base"
  | "artifact"
  | "member"
  | "invitation"
  | "group"
  | "organization"
  | "trigger"
  | "channel"
  | "notification"
  | "secret"
  | "mcp_connection"
  | "run"
  | "eval_suite";

export type ChangeAction = "created" | "updated" | "deleted";

/** A console session, an organization API key, an MCP client signed in over
 *  OAuth, or the in-app Architect. */
export type ChangeSurface = "console" | "api_key" | "mcp" | "assistant";

interface ChangeEventBase {
  organization_id: string;
  resource: ChangeResource;
  /** The changed row; null when the write did not name one. */
  id: string | null;
  action: ChangeAction;
  /** The console tab that made the change, when one did (`X-Console-Tab`). */
  origin_tab: string | null;
}

/** A change somebody made: a write through the console, a key, MCP or the Architect. */
export interface MadeChange extends ChangeEventBase {
  surface: ChangeSurface;
  actor_user_id: string;
  actor_name: string;
}

/** A run moving through its states - started, parked, finished - or an eval suite's
 *  result settling, which nobody wrote. */
export interface RunChange extends ChangeEventBase {
  resource: "run" | "eval_suite";
  surface: "run";
  /** The member the run acts as, when it acts as one. */
  actor_user_id: string | null;
  actor_name: null;
}

export type ChangeEvent = MadeChange | RunChange;
