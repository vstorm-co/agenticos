import type { McpCatalogEntry } from "@/types/mcp";
import { connectorBrand } from "@/components/icons/brand-icon";
import { type BrandName, brandMark } from "@/components/icons/brand-icon";

/**
 * A service the step picker groups by: its native trigger and the actions of
 * the organization's MCP connections to it, side by side.
 *
 * The one place that knows which trigger belongs with which MCP server. It is
 * the picker's own mapping - a portal's `mcp_catalog_key` means "connects
 * through that catalog entry's OAuth", a different thing - and it changes
 * nothing underneath: an action is still an `mcp.call`.
 */
export interface WorkflowApp {
  /** The picker group's id, also its `category.<id>` and `appServer.<id>` message keys. */
  id: string;
  brand?: BrandName;
  /** Catalog name for apps without curated translations. */
  name?: string;
  /** The definition ids of the app's native triggers. */
  triggers: readonly string[];
  /**
   * The server's own group: the one a tool no other app of the server claims falls into,
   * and the only one that offers Connect or names an untested connection.
   */
  fallback: boolean;
  /** The MCP catalog keys whose connections provide the app's actions. */
  catalogKeys: readonly [string, ...string[]];
  /** The common tools by their raw name, to the `workflows.appTool` message that names them. */
  tools: Readonly<Record<string, string>>;
  /**
   * Per tool, the arguments a new step starts bound to the app's trigger, each to the
   * trigger output field it reads - the mail being answered. Only tools that act on the
   * message the trigger delivered are listed.
   */
  suggestedBindings: Readonly<Record<string, Readonly<Record<string, string>>>>;
}

export const WORKFLOW_APPS: readonly WorkflowApp[] = [
  {
    id: "gmail",
    brand: "gmail",
    fallback: false,
    triggers: ["trigger.gmail"],
    catalogKeys: ["google-workspace"],
    tools: {
      get_gmail_message_content: "appTool.readMessage",
      get_gmail_messages_content_batch: "appTool.readMessages",
      get_gmail_attachment_content: "appTool.readAttachment",
      get_gmail_thread_content: "appTool.readThread",
      get_gmail_threads_content_batch: "appTool.readThreads",
      search_gmail_messages: "appTool.searchMail",
      list_gmail_labels: "appTool.listLabels",
      manage_gmail_label: "appTool.manageLabel",
      list_gmail_filters: "appTool.listFilters",
      manage_gmail_filter: "appTool.manageFilter",
      modify_gmail_message_labels: "appTool.changeLabels",
      batch_modify_gmail_message_labels: "appTool.changeLabelsBatch",
      draft_gmail_message: "appTool.createDraft",
      send_gmail_message: "appTool.sendMessage",
    },
    suggestedBindings: {
      draft_gmail_message: { thread_id: "thread_id", in_reply_to: "rfc_message_id" },
      send_gmail_message: { thread_id: "thread_id", in_reply_to: "rfc_message_id", to: "sender" },
    },
  },
  {
    id: "google_calendar",
    brand: "googlecalendar",
    fallback: false,
    triggers: [],
    catalogKeys: ["google-workspace"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "google_drive",
    brand: "gdrive",
    fallback: false,
    triggers: [],
    catalogKeys: ["google-workspace"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "google_docs",
    brand: "google",
    fallback: false,
    triggers: [],
    catalogKeys: ["google-workspace"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "google_sheets",
    brand: "google",
    fallback: false,
    triggers: [],
    catalogKeys: ["google-workspace"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "google_workspace",
    brand: "google",
    fallback: true,
    triggers: [],
    catalogKeys: ["google-workspace"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "outlook",
    brand: "microsoft",
    fallback: false,
    triggers: ["trigger.outlook"],
    catalogKeys: ["ms-365"],
    tools: {
      "create-reply-draft": "appTool.createReplyDraft",
      "create-shared-mailbox-reply-draft": "appTool.createSharedReplyDraft",
      "send-draft-message": "appTool.sendDraft",
      "send-shared-mailbox-draft": "appTool.sendSharedDraft",
    },
    // A sent draft's `messageId` is the draft step's result, not the trigger's mail.
    suggestedBindings: {
      "create-reply-draft": { messageId: "message_id" },
      "create-shared-mailbox-reply-draft": { messageId: "message_id", userId: "mailbox" },
      "send-shared-mailbox-draft": { userId: "mailbox" },
    },
  },
  {
    id: "outlook_calendar",
    brand: "microsoft",
    fallback: false,
    triggers: [],
    catalogKeys: ["ms-365"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "onedrive",
    brand: "onedrive",
    fallback: false,
    triggers: [],
    catalogKeys: ["ms-365"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "excel",
    brand: "microsoft",
    fallback: false,
    triggers: [],
    catalogKeys: ["ms-365"],
    tools: {},
    suggestedBindings: {},
  },
  {
    id: "microsoft_365",
    brand: "microsoft",
    fallback: true,
    triggers: [],
    catalogKeys: ["ms-365"],
    tools: {},
    suggestedBindings: {},
  },
];

/** A step's own group marks: what the picker and the cards draw for the app. */
export const APP_MARKS = Object.fromEntries(
  WORKFLOW_APPS.flatMap((app) => (app.brand === undefined ? [] : [[app.id, brandMark(app.brand)]])),
);

/** The sign-in tools of the servers: a step never offers them, the connection handles signing in. */
export const LOGIN_TOOLS: ReadonlySet<string> = new Set([
  "start_google_auth",
  "login",
  "logout",
  "verify-login",
]);

/** Tools the name heuristic cannot place, by the app they belong to. */
const TOOL_GROUPS: Readonly<Record<string, string>> = {
  get_events: "google_calendar",
  manage_event: "google_calendar",
  query_freebusy: "google_calendar",
  search_drive_files: "google_drive",
  get_drive_file_content: "google_drive",
  append_table_rows: "google_sheets",
  read_sheet_values: "google_sheets",
  "list-calendar-events": "outlook_calendar",
  "create-calendar-event": "outlook_calendar",
};

/** Per server, the words in a tool's name that place it in an app; the first rule to match wins. */
const TOOL_TOKENS: Readonly<Record<string, readonly (readonly [string, readonly string[]])[]>> = {
  "google-workspace": [
    ["gmail", ["gmail"]],
    ["google_calendar", ["calendar", "calendars", "event", "events", "freebusy"]],
    ["google_sheets", ["sheet", "sheets", "spreadsheet", "spreadsheets"]],
    ["google_docs", ["doc", "docs", "document", "documents"]],
    ["google_drive", ["drive", "file", "files", "folder", "folders"]],
  ],
  "ms-365": [
    ["excel", ["excel", "workbook", "worksheet", "worksheets"]],
    ["outlook_calendar", ["calendar", "calendars", "event", "events", "meeting", "meetings"]],
    ["outlook", ["mail", "email", "message", "messages", "draft", "drafts", "mailbox", "inbox"]],
    ["onedrive", ["drive", "drives", "file", "files", "folder", "folders"]],
  ],
};

/**
 * The app a tool of a connection to this catalog entry belongs to. With no tool named,
 * the server's own group; a sign-in tool, none; otherwise the app that lists the tool,
 * then the explicit table, then the words in its name, then the server's own group.
 * Null for a catalog entry no app covers.
 */
export function appForCatalogKey(catalogKey: string | null, tool?: string): WorkflowApp | null {
  if (catalogKey === null) return null;
  const apps = WORKFLOW_APPS.filter((app) => app.catalogKeys.includes(catalogKey));
  const fallback = apps.find((app) => app.fallback);
  if (fallback === undefined) return null;
  if (tool === undefined || tool === "") return fallback;
  if (LOGIN_TOOLS.has(tool)) return null;
  const listed = apps.find(
    (app) => Object.hasOwn(app.tools, tool) || Object.hasOwn(app.suggestedBindings, tool),
  );
  if (listed !== undefined) return listed;
  const byId = (id: string | undefined) => apps.find((app) => app.id === id);
  const explicit = byId(TOOL_GROUPS[tool]);
  if (explicit !== undefined) return explicit;
  const words = new Set(tool.toLowerCase().split(/[_\-.]+/));
  const rule = (TOOL_TOKENS[catalogKey] ?? []).find(([, tokens]) =>
    tokens.some((token) => words.has(token)),
  );
  return byId(rule?.[0]) ?? fallback;
}

/** The id of the server's own group that `app`'s connections belong to: what names its server. */
export function serverGroupId(app: WorkflowApp): string {
  const own = WORKFLOW_APPS.find(
    (one) => one.fallback && one.catalogKeys[0] === app.catalogKeys[0],
  );
  // i18n-exempt: a registry invariant, never shown.
  if (own === undefined) throw new Error(`No server group for the app ${app.id}`);
  return own.id;
}

/** `list_gmail_labels` as "List gmail labels": a tool nobody named gets its own name, readable. */
export function humanizeTool(tool: string): string {
  const words = tool.replace(/[_-]+/g, " ").trim();
  return words === "" ? tool : words.charAt(0).toUpperCase() + words.slice(1);
}

/** A tool's name for a person: the curated one where the app has it, else its own, humanized. */
export function appToolLabel(app: WorkflowApp, tool: string, t: (key: string) => string): string {
  const key = app.tools[tool];
  return key === undefined ? humanizeTool(tool) : t(key);
}

/** The trigger a tool's suggested bindings read from, and which trigger field fills each argument. */
export function suggestedBindingsFor(
  tool: string,
): { triggers: readonly string[]; fields: Readonly<Record<string, string>> } | null {
  for (const app of WORKFLOW_APPS) {
    const fields = app.suggestedBindings[tool];
    if (fields !== undefined) return { triggers: app.triggers, fields };
  }
  return null;
}

/** A catalog service keeps its own name without requiring a hardcoded app registry. */
export function catalogWorkflowApp(entry: McpCatalogEntry): WorkflowApp {
  return {
    id: `mcp:${entry.key}`,
    name: entry.name,
    brand: connectorBrand(entry.icon ?? entry.key),
    triggers: [],
    fallback: true,
    catalogKeys: [entry.key],
    tools: {},
    suggestedBindings: {},
  };
}
