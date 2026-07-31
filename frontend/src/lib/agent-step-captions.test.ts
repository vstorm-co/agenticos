import { describe, expect, it } from "vitest";

import { toolCaption, toolDisplayName } from "./agent-step-captions";

/**
 * What the chat says an agent is doing while a tool runs.
 *
 * Three layers, and the order between them is the whole design: a named tool
 * gets the sentence somebody wrote for it, an unnamed one falls back to its
 * prefix, and anything else is humanised rather than printed as
 * `create_invoice_tool`. A registry-driven capability can add a tool the day
 * after this file was last touched, so the fallback is the common path rather
 * than the exceptional one.
 */
describe("toolCaption", () => {
  it("uses the sentence written for a tool it knows", () => {
    expect(toolCaption("search_knowledge_base")).toBe("Searching the knowledge base");
    expect(toolCaption("ask_user")).toBe("Asking you a question");
  });

  it("falls back to the prefix for a tool nobody named", () => {
    // `generate_pie_chart` is not in the list and never will be; the prefix is
    // what makes a new chart tool narrate correctly on the day it ships.
    expect(toolCaption("generate_pie_chart")).toBe("Generating a chart");
    expect(toolCaption("search_invoices")).toBe("Searching");
    expect(toolCaption("create_ticket")).toBe("Creating");
    expect(toolCaption("fetch_orders")).toBe("Fetching data");
    expect(toolCaption("get_balance")).toBe("Looking that up");
    expect(toolCaption("list_projects")).toBe("Looking that up");
  });

  it("prefers the exact caption over a prefix that also matches", () => {
    // `search_documents` starts with `search_`, and "Searching" would be a
    // worse answer than the one somebody wrote for it.
    expect(toolCaption("search_documents")).toBe("Searching the documents");
  });

  it("humanises a tool it has never heard of rather than printing its id", () => {
    expect(toolCaption("post_invoice")).toBe("Running Post Invoice");
    // The `_tool` suffix is an implementation detail of how capabilities name
    // their tools, not something to read out.
    expect(toolCaption("send_slack_message_tool")).toBe("Running Send Slack Message");
  });

  it("prints a nameless tool as it arrived rather than as an empty caption", () => {
    // Reachable from a malformed stream frame; "Running " is worse than nothing.
    expect(toolCaption("_")).toBe("Running _");
  });
});

describe("toolDisplayName", () => {
  it("uses the label written for a tool it knows", () => {
    expect(toolDisplayName("run_python")).toBe("Run Python");
    expect(toolDisplayName("search_documents")).toBe("Knowledge Base Search");
  });

  it("humanises anything else", () => {
    expect(toolDisplayName("post_invoice")).toBe("Post Invoice");
    expect(toolDisplayName("create_invoice_tool")).toBe("Create Invoice");
  });
});
