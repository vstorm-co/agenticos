import messages from "../../../messages/en.json";
import { describe, expect, it } from "vitest";

import {
  appForCatalogKey,
  appToolLabel,
  humanizeTool,
  serverGroupId,
  suggestedBindingsFor,
  WORKFLOW_APPS,
} from "./apps";

describe("the apps registry", () => {
  it.each([
    ["google-workspace", "draft_gmail_message", "gmail"],
    ["google-workspace", "get_events", "google_calendar"],
    ["google-workspace", "manage_event", "google_calendar"],
    ["google-workspace", "query_freebusy", "google_calendar"],
    ["google-workspace", "list_calendars", "google_calendar"],
    ["google-workspace", "search_drive_files", "google_drive"],
    ["google-workspace", "get_drive_file_content", "google_drive"],
    ["google-workspace", "append_table_rows", "google_sheets"],
    ["google-workspace", "read_sheet_values", "google_sheets"],
    ["google-workspace", "create_spreadsheet", "google_sheets"],
    ["google-workspace", "get_doc_content", "google_docs"],
    ["google-workspace", "search_custom", "google_workspace"],
    ["ms-365", "create-reply-draft", "outlook"],
    ["ms-365", "send-shared-mailbox-draft", "outlook"],
    ["ms-365", "list-mail-folders", "outlook"],
    ["ms-365", "list-calendar-events", "outlook_calendar"],
    ["ms-365", "create-calendar-event", "outlook_calendar"],
    ["ms-365", "list-excel-worksheets", "excel"],
    ["ms-365", "list-folder-files", "onedrive"],
    ["ms-365", "list-planner-tasks", "microsoft_365"],
    ["ms-365", "constructor", "microsoft_365"],
    ["google-workspace", "toString", "google_workspace"],
  ])("puts %s's %s under %s", (key, tool, app) => {
    expect(appForCatalogKey(key, tool)?.id).toBe(app);
  });

  it("gives a connection with no tool named its server's own group, and nothing to another server", () => {
    expect(appForCatalogKey("google-workspace")?.id).toBe("google_workspace");
    expect(appForCatalogKey("ms-365", "")?.id).toBe("microsoft_365");
    expect(appForCatalogKey("hubspot", "x")).toBeNull();
    expect(appForCatalogKey(null, "get_events")).toBeNull();
  });

  it.each(["start_google_auth", "login", "verify-login"])(
    "offers no group for the sign-in tool %s",
    (tool) => {
      expect(appForCatalogKey("google-workspace", tool)).toBeNull();
      expect(appForCatalogKey("ms-365", tool)).toBeNull();
    },
  );

  it("pairs each app with its trigger and holds each tool's label key once", () => {
    expect(WORKFLOW_APPS.map((app) => [app.id, app.triggers])).toEqual([
      ["gmail", ["trigger.gmail"]],
      ["google_calendar", []],
      ["google_drive", []],
      ["google_docs", []],
      ["google_sheets", []],
      ["google_workspace", []],
      ["outlook", ["trigger.outlook"]],
      ["outlook_calendar", []],
      ["onedrive", []],
      ["excel", []],
      ["microsoft_365", []],
    ]);
    for (const key of ["google-workspace", "ms-365"]) {
      const own = WORKFLOW_APPS.filter((app) => app.catalogKeys.includes(key));
      expect(own.filter((app) => app.fallback)).toHaveLength(1);
    }
    const keys = WORKFLOW_APPS.flatMap((app) => Object.values(app.tools));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("names every tool the Google Workspace server offers for Gmail by its curated label", () => {
    const gmail = WORKFLOW_APPS[0] as (typeof WORKFLOW_APPS)[number];
    const t = (key: string) =>
      (messages.workflows.appTool as Record<string, string>)[key.replace("appTool.", "")] ?? key;
    const labels = {
      get_gmail_message_content: "Read message",
      get_gmail_messages_content_batch: "Read messages",
      get_gmail_attachment_content: "Read attachment",
      get_gmail_thread_content: "Read thread",
      get_gmail_threads_content_batch: "Read threads",
      search_gmail_messages: "Search mail",
      list_gmail_labels: "List labels",
      manage_gmail_label: "Manage label",
      list_gmail_filters: "List filters",
      manage_gmail_filter: "Manage filter",
      modify_gmail_message_labels: "Change labels",
      batch_modify_gmail_message_labels: "Change labels on several",
      draft_gmail_message: "Create draft",
      send_gmail_message: "Send message",
    };
    for (const [tool, label] of Object.entries(labels)) {
      expect(appToolLabel(gmail, tool, t)).toBe(label);
    }
  });

  it("names a common tool by its label and any other by its own name, humanized", () => {
    const gmail = WORKFLOW_APPS[0] as (typeof WORKFLOW_APPS)[number];
    const t = (key: string) => `[${key}]`;
    expect(appToolLabel(gmail, "draft_gmail_message", t)).toBe("[appTool.createDraft]");
    expect(appToolLabel(gmail, "list_gmail_drafts", t)).toBe("List gmail drafts");
    expect(humanizeTool("send-draft-message")).toBe("Send draft message");
    expect(humanizeTool("__")).toBe("__");
  });
});

describe("suggestedBindingsFor", () => {
  it("names the trigger and the fields a mail tool starts bound to", () => {
    expect(suggestedBindingsFor("send_gmail_message")).toEqual({
      triggers: ["trigger.gmail"],
      fields: { thread_id: "thread_id", in_reply_to: "rfc_message_id", to: "sender" },
    });
    expect(suggestedBindingsFor("send-shared-mailbox-draft")?.fields).toEqual({
      userId: "mailbox",
    });
  });

  it("has nothing for a tool that does not act on the delivered mail", () => {
    expect(suggestedBindingsFor("list_gmail_labels")).toBeNull();
  });
});

describe("serverGroupId", () => {
  it("names the server's own group, and throws for an app no server group covers", () => {
    const sheets = WORKFLOW_APPS.find((app) => app.id === "google_sheets");
    expect(sheets && serverGroupId(sheets)).toBe("google_workspace");
    const orphan = { ...WORKFLOW_APPS[0]!, catalogKeys: ["nowhere"] as const };
    expect(() => serverGroupId(orphan)).toThrow(/nowhere|server group/);
  });
});
