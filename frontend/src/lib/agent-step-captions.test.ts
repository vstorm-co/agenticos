import { describe, expect, it } from "vitest";

import { toolCaption, toolDisplayName } from "./agent-step-captions";

import { createTranslator } from "next-intl";

import type { Translate } from "./agent-step-captions";
import messages from "../../messages/en.json";

/**
 * The real `chat.tools` messages: a step's wording is what these tests are about, and
 * resolving them here also proves every key the catalog table names exists.
 *
 * Cast because `createTranslator` types its key against the message tree while
 * `Translate` takes the string a module table holds - the looseness #395's parser
 * would remove.
 */
const t = createTranslator({ locale: "en", messages, namespace: "chat.tools" }) as Translate;

/**
 * What the chat says an agent is doing while a tool runs.
 *
 * Three layers, and the order between them is the whole design: a named tool
 * gets the sentence somebody wrote for it, an unnamed one falls back to its
 * prefix, and anything else is humanised rather than printed as
 * `create_invoice`. The wording for a named tool lives in `tool-catalog.ts` with the
 * rest of what this side knows about it; what is tested here is the order the three
 * layers are consulted in. A binding can rename a tool and an MCP server can expose
 * anything at all, so the fallback is the common path rather than the exceptional one.
 */
describe("toolCaption", () => {
  it("uses the sentence written for a tool it knows", () => {
    expect(toolCaption("web_search", t)).toBe("Searching the web");
    expect(toolCaption("create_chart", t)).toBe("Creating a chart");
  });

  it("falls back to the prefix for a tool nobody named", () => {
    // `generate_pie_chart` is not in the list and never will be; the prefix is
    // what makes a new chart tool narrate correctly on the day it ships.
    expect(toolCaption("generate_pie_chart", t)).toBe("Generating a chart");
    expect(toolCaption("search_invoices", t)).toBe("Searching");
    expect(toolCaption("create_ticket", t)).toBe("Creating");
    expect(toolCaption("fetch_orders", t)).toBe("Fetching data");
    expect(toolCaption("get_balance", t)).toBe("Looking that up");
    expect(toolCaption("list_projects", t)).toBe("Looking that up");
  });

  it("prefers the exact caption over a prefix that also matches", () => {
    // `search_documents` starts with `search_`, and "Searching" would be a
    // worse answer than the one somebody wrote for it.
    expect(toolCaption("search_documents", t)).toBe("Searching the documents");
  });

  it("humanises a tool it has never heard of rather than printing its id", () => {
    expect(toolCaption("post_invoice", t)).toBe("Running Post Invoice");
  });

  it("prints a nameless tool as it arrived rather than as an empty caption", () => {
    // Reachable from a malformed stream frame; "Running " is worse than nothing.
    expect(toolCaption("_", t)).toBe("Running _");
  });
});

describe("toolDisplayName", () => {
  it("uses the label written for a tool it knows", () => {
    expect(toolDisplayName("run_python", t)).toBe("Run Python");
    expect(toolDisplayName("search_documents", t)).toBe("Knowledge Base Search");
  });

  it("humanises anything else", () => {
    expect(toolDisplayName("post_invoice", t)).toBe("Post Invoice");
    expect(toolDisplayName("linear_create_issue", t)).toBe("Linear Create Issue");
  });
});
