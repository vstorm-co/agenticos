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
  | "organization";

export type ChangeAction = "created" | "updated" | "deleted";

/** A console session, an organization API key, an MCP client signed in over
 *  OAuth, or the in-app Platform assistant. */
export type ChangeSurface = "console" | "api_key" | "mcp" | "assistant";

export interface ChangeEvent {
  organization_id: string;
  resource: ChangeResource;
  /** The changed row; null when the write did not name one. */
  id: string | null;
  action: ChangeAction;
  surface: ChangeSurface;
  actor_user_id: string;
  actor_name: string;
  /** The console tab that made the change, when one did (`X-Console-Tab`). */
  origin_tab: string | null;
}
