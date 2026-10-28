import { describe, expect, it } from "vitest";

import { makeDefinition } from "@/components/workflows/validation/fixtures";

import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

import { MORE_SECTION, matchesAction, matchesSearch, pickerSections } from "./groups";

const step = (id: string, category: string, name = id) =>
  makeDefinition({ id, category, name, description: `does ${name}` });

describe("pickerSections", () => {
  it("groups steps into sections in reading order, a platform acting first", () => {
    const sections = pickerSections([
      step("slack.channels.find", "slack"),
      step("slack.message.send", "slack"),
      step("core.input", "triggers"),
      step("debug.echo", "debug"),
      step("custom.thing", "custom"),
      step("table.record.get", "tables"),
    ]);

    expect(sections.map((section) => section.id)).toEqual(["start", "data", "apps", MORE_SECTION]);
    const slack = sections.find((section) => section.id === "apps")?.groups[0];
    expect(slack?.items.map((item) => item.id)).toEqual([
      "slack.message.send",
      "slack.channels.find",
    ]);
    // A category no section names comes last, and a hidden one never shows.
    expect(sections.at(-1)?.groups.map((group) => group.category)).toEqual(["custom"]);
    expect(sections.flatMap((s) => s.groups).some((g) => g.category === "debug")).toBe(false);
  });

  it("sorts the categories no section names by their rank, then by name", () => {
    const sections = pickerSections([step("b.one", "zeta"), step("a.one", "alpha")]);
    expect(sections[0]?.groups.map((group) => group.category)).toEqual(["alpha", "zeta"]);
  });
});

describe("matchesSearch", () => {
  it("finds a step by its name, what it does or its group, ignoring case", () => {
    const send = step("slack.message.send", "slack", "Send a message");
    expect(matchesSearch(send, "", "Slack")).toBe(true);
    expect(matchesSearch(send, "SEND", "Slack")).toBe(true);
    expect(matchesSearch(send, "does send", "Slack")).toBe(true);
    expect(matchesSearch(send, "slack", "Slack")).toBe(true);
    expect(matchesSearch(send, "table", "Slack")).toBe(false);
    // Every word, in any order, each in any field.
    expect(matchesSearch(send, "send slack", "Slack")).toBe(true);
    expect(matchesSearch(send, "slack message", "Slack")).toBe(true);
    expect(matchesSearch(send, "slack zebra", "Slack")).toBe(false);
    expect(matchesSearch(send, "message.send", "Slack")).toBe(true);
  });
});

describe("pickerSections with apps", () => {
  const conn = (overrides: Partial<UsableMcpConnectionRecord> = {}) =>
    ({
      id: "c1",
      name: "gmail-dev",
      label: null,
      catalog_key: "google-workspace",
      is_enabled: true,
      allowed_tools: null,
      last_tools: [{ name: "draft_gmail_message", description: "Draft" }],
      ...overrides,
    }) as UsableMcpConnectionRecord;
  const defs = [step("trigger.gmail", "triggers"), step("mcp.call", "mcp")];
  const gmailGroup = (
    connections: UsableMcpConnectionRecord[] | null,
    canConnect = false,
    d = defs,
  ) =>
    pickerSections(d, { connections, canConnect })
      .find((section) => section.id === "apps")
      ?.groups.find((group) => group.category === "gmail");

  it("puts an app first in Apps, holding its trigger and its connection's tools", () => {
    const apps = pickerSections(defs, { connections: [conn()], canConnect: true }).find(
      (section) => section.id === "apps",
    );
    expect(apps?.groups.map((group) => group.category)).toEqual(["gmail", "outlook", "mcp"]);
    const group = apps?.groups[0];
    expect(group?.items.map((item) => item.id)).toEqual(["trigger.gmail"]);
    expect(group?.app?.actions.map((action) => [action.connectionId, action.tool])).toEqual([
      ["c1", "draft_gmail_message"],
    ]);
    expect(group?.app?.connectKey).toBeNull();
    // The trigger stays under Triggers as well.
    expect(
      pickerSections(defs).find((section) => section.id === "start")?.groups[0]?.items,
    ).toHaveLength(1);
  });

  it("offers to connect only a member who may, and only once the list is known to hold none", () => {
    expect(gmailGroup([], true)?.app?.connectKey).toBe("google-workspace");
    expect(gmailGroup([], false)?.app?.connectKey).toBeNull();
    expect(gmailGroup(null, true)?.app?.connectKey).toBeNull();
    expect(gmailGroup([conn({ catalog_key: "hubspot" })], true)?.app?.connectKey).toBe(
      "google-workspace",
    );
    // Nothing to connect through when the canvas offers no MCP call.
    expect(gmailGroup([], true, [step("trigger.gmail", "triggers")])?.app?.connectKey).toBeNull();
  });

  it("leaves a disabled connection and held-back tools out, and notes one with no tools", () => {
    const group = gmailGroup([
      conn({ allowed_tools: ["other"] }),
      conn({ id: "c2", is_enabled: false }),
      conn({ id: "c3", name: "fresh", last_tools: null, label: "Fresh" }),
    ]);
    expect(group?.app?.actions).toEqual([]);
    expect(group?.app?.untested).toEqual([
      { id: "c1", name: "gmail-dev" },
      { id: "c3", name: "Fresh" },
    ]);
  });

  it("says why when this member may not edit workflows, not when the list is just loading", () => {
    const state = (connections: UsableMcpConnectionRecord[] | null, unavailable: boolean) =>
      pickerSections(defs, { connections, canConnect: false, unavailable }).find(
        (section) => section.id === "apps",
      )?.groups[0]?.app?.needsPermission;
    expect(state(null, true)).toBe(true);
    expect(state(null, false)).toBe(false);
    expect(state([], false)).toBe(false);
  });

  it("has no group for an app with nothing to show", () => {
    expect(gmailGroup([], false, [step("mcp.call", "mcp")])).toBeUndefined();
    expect(gmailGroup(null, true, [step("mcp.call", "mcp")])).toBeUndefined();
    expect(gmailGroup(null, false, [step("trigger.gmail", "triggers")])?.app?.actions).toEqual([]);
  });

  it("matches an action by its label, tool, description, app or connection", () => {
    const action = gmailGroup([conn()])?.app?.actions[0];
    if (action === undefined) throw new Error("no action");
    expect(matchesAction(action, "", "Create draft", "Gmail")).toBe(true);
    for (const query of ["create dr", "DRAFT_GMAIL", "draft", "gmail", "dev"]) {
      expect(matchesAction(action, query, "Create draft", "Gmail")).toBe(true);
    }
    expect(matchesAction(action, "slack", "Create draft", "Gmail")).toBe(false);
  });

  it("matches when every word occurs in any field, in any order", () => {
    const read = gmailGroup([
      conn({ last_tools: [{ name: "get_gmail_message_content", description: "" }] }),
    ])?.app?.actions[0];
    const draft = gmailGroup([conn()])?.app?.actions[0];
    const thread = gmailGroup([
      conn({ last_tools: [{ name: "get_gmail_thread_content", description: "" }] }),
    ])?.app?.actions[0];
    if (read === undefined || draft === undefined || thread === undefined) throw new Error("none");

    expect(matchesAction(read, "gmail read mess", "Read message", "Gmail")).toBe(true);
    expect(matchesAction(read, "mess read gmail", "Read message", "Gmail")).toBe(true);
    // The tool's own name, its underscores read as spaces.
    expect(matchesAction(read, "message content", "Read message", "Gmail")).toBe(true);
    expect(matchesAction(thread, "read thread", "Read thread", "Gmail")).toBe(true);
    expect(matchesAction(draft, "draft gmail", "Create draft", "Gmail")).toBe(true);
    expect(matchesAction(draft, "gmail nothing", "Create draft", "Gmail")).toBe(false);
    expect(matchesAction(draft, "  ", "Create draft", "Gmail")).toBe(true);
  });
});
