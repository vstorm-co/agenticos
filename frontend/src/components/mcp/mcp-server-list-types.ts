import type { McpConnectionRecord, McpToolInfo } from "@/lib/mcp-connections-api";
import type { McpServerRow } from "@/lib/mcp-servers";

/**
 * The shapes shared between `McpServerList` and its two dialogs.
 *
 * A leaf module, so the dialogs read them without importing the component that
 * renders them - a value cycle (`SCOPE_LABEL`) the other way around would
 * otherwise run the dialog module while the list module was still initializing.
 */

/** Who a connection belongs to. The whole of what the two columns mean. */
export type Scope = "organization" | "personal";

/**
 * How a server checks who is calling.
 *
 * The three the platform can do, in either scope. An organization connection
 * may hold an OAuth grant: the common case is a shared service account that one
 * admin consents with and everybody's agents then use. The grant is still that
 * account's at the provider, which is a real operational cost - the dialog says
 * so where the choice is made rather than withholding the choice.
 */
export type DraftAuth = "none" | "token" | "oauth";

/** Keys, not translations: a module constant has no translator to reach. */
export const SCOPE_LABEL: Record<Scope, string> = {
  organization: "scopeOrganization",
  personal: "scopeYou",
};

export interface DraftState {
  scope: Scope;
  row: McpServerRow;
  /** The connection being edited, or null when connecting for the first time. */
  existing: McpConnectionRecord | null;
  /**
   * What to seed the name with, where the entry's own key is taken.
   *
   * Connecting a *second* account for one server would otherwise open on the
   * name the first one already holds, and names are unique per organization -
   * so the form's first submit was a guaranteed conflict.
   */
  suggestedName?: string;
}

/**
 * The fields the connection dialog collects, handed to the list on submit.
 *
 * The dialog owns this while it is open and seeds it from the `DraftState`; the
 * list reads it back in one object rather than holding a `useState` per field
 * and drilling a setter each into the dialog.
 */
export interface ConnectionFormValues {
  name: string;
  url: string;
  token: string;
  auth: DraftAuth;
  clearToken: boolean;
  scope: Scope;
}

/** A probed connection and which of its tools are currently checked. */
export interface ToolPickerState {
  scope: Scope;
  connection: McpConnectionRecord;
  tools: McpToolInfo[];
  checked: Set<string>;
}
