import messages from "../../../messages/en.json";
import { describe, expect, it } from "vitest";

import {
  appForCatalogKey,
  appToolLabel,
  humanizeTool,
  suggestedBindingsFor,
  WORKFLOW_APPS,
} from "./apps";

describe("the apps registry", () => {
  it("maps an MCP catalog entry to the app its connections provide", () => {
    expect(appForCatalogKey("google-workspace")?.id).toBe("gmail");
    expect(appForCatalogKey("ms-365")?.id).toBe("outlook");
    expect(appForCatalogKey("hubspot")).toBeNull();
    expect(appForCatalogKey(null)).toBeNull();
  });

  it("pairs each app with its trigger and holds each tool's label key once", () => {
    expect(WORKFLOW_APPS.map((app) => app.triggers)).toEqual([
      ["trigger.gmail"],
      ["trigger.outlook"],
    ]);
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
      start_google_auth: "Start Google sign-in",
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
