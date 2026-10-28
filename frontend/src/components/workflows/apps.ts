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
  brand: BrandName;
  /** The definition ids of the app's native triggers. */
  triggers: readonly string[];
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
      start_google_auth: "appTool.startGoogleSignIn",
    },
    suggestedBindings: {
      draft_gmail_message: { thread_id: "thread_id", in_reply_to: "rfc_message_id" },
      send_gmail_message: { thread_id: "thread_id", in_reply_to: "rfc_message_id", to: "sender" },
    },
  },
  {
    id: "outlook",
    brand: "microsoft",
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
];

/** A step's own group marks: what the picker and the cards draw for the app. */
export const APP_MARKS = Object.fromEntries(
  WORKFLOW_APPS.map((app) => [app.id, brandMark(app.brand)]),
);

/** The app whose actions a connection to this catalog entry provides, if any. */
export function appForCatalogKey(catalogKey: string | null): WorkflowApp | null {
  if (catalogKey === null) return null;
  return WORKFLOW_APPS.find((app) => app.catalogKeys.includes(catalogKey)) ?? null;
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
