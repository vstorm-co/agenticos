import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assistantPagePath,
  assistantPageSnapshot,
  sanitizeAssistantPageDetails,
} from "./assistant-page-context";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("assistantPagePath", () => {
  it.each([
    ["/pl/apps/scheduler?api_key=private#selected", "/apps/scheduler"],
    ["/DE/agents/agent-1", "/agents/agent-1"],
    ["/de", "/"],
    ["/apps/scheduler#record-1", "/apps/scheduler"],
    ["/apps/scheduler", "/apps/scheduler"],
    ["/", "/"],
  ])("keeps only the in-app route from %s", (input, expected) => {
    expect(assistantPagePath(input)).toBe(expected);
  });

  it.each([
    "",
    "apps/scheduler",
    "https://example.com/apps/scheduler",
    "//example.com/apps/scheduler",
    "/\\example.com/apps",
    "/apps\nprivate",
    "/apps\u0000private",
    "/apps\u007fprivate",
    "/pl//example.com",
  ])("does not attach an unsafe route: %j", (input) => {
    expect(assistantPagePath(input)).toBe("/");
  });

  it("bounds the route without bringing query values back into it", () => {
    const path = "/" + "a".repeat(2100);
    expect(assistantPagePath(path + "?token=private")).toBe(path.slice(0, 2048));
  });
});

describe("sanitizeAssistantPageDetails", () => {
  it.each([undefined, null, [], false, 12, "page"])(
    "ignores a value that is not a details object: %j",
    (input) => {
      expect(sanitizeAssistantPageDetails(input)).toEqual({});
    },
  );

  it("omits malformed and empty details instead of sending invalid field types", () => {
    expect(
      sanitizeAssistantPageDetails({
        title: 7,
        resource: { kind: "app" },
        view: false,
        filters: [],
        selected_ids: [null, 7, "", "  "],
        summary: {},
        selected_text: " ",
      }),
    ).toEqual({});
    expect(
      sanitizeAssistantPageDetails({
        title: " ",
        resource: { kind: "", id: "scheduler" },
        filters: { count: 3, " ": "empty key" },
        selected_ids: [],
      }),
    ).toEqual({});
  });

  it("keeps every text and collection within the backend contract", () => {
    const filters = Object.fromEntries(
      Array.from({ length: 22 }, (_, index) => [
        "k".repeat(78) + String(index).padStart(2, "0"),
        "f".repeat(241),
      ]),
    );
    const details = sanitizeAssistantPageDetails({
      title: "t".repeat(241),
      resource: {
        kind: "k".repeat(65),
        id: "i".repeat(129),
        title: "r".repeat(241),
      },
      view: "v".repeat(121),
      filters,
      selected_ids: Array.from({ length: 22 }, () => "i".repeat(129)),
      summary: "s".repeat(6001),
      selected_text: "q".repeat(2001),
    });

    expect(details.title).toBe("t".repeat(240));
    expect(details.resource).toEqual({
      kind: "k".repeat(64),
      id: "i".repeat(128),
      title: "r".repeat(240),
    });
    expect(details.view).toBe("v".repeat(120));
    expect(Object.keys(details.filters ?? {})).toEqual(Object.keys(filters).slice(0, 20));
    expect(Object.values(details.filters ?? {})).toEqual(Array(20).fill("f".repeat(240)));
    expect(details.selected_ids).toEqual(Array(20).fill("i".repeat(128)));
    expect(details.summary).toBe("s".repeat(6000));
    expect(details.selected_text).toBe("q".repeat(2000));
  });

  it("omits sensitive, invalid and prototype-related filter keys", () => {
    const filters = Object.fromEntries([
      ["status", ""],
      ["version", "3"],
      ["password", "private"],
      ["client_secret", "private"],
      ["access_token", "private"],
      ["Authorization", "private"],
      ["Cookie", "private"],
      ["API_key", "private"],
      ["api-key", "private"],
      ["__proto__", "private"],
      ["constructor", "private"],
      ["prototype", "private"],
      ["x".repeat(81), "too long"],
      ["count", 3],
    ]);

    expect(sanitizeAssistantPageDetails({ filters })).toEqual({
      filters: { status: "", version: "3" },
    });
  });

  it("copies only declared page fields and never accepts identity or permission overrides", () => {
    expect(
      sanitizeAssistantPageDetails({
        path: "https://example.com/private",
        captured_at: "forged",
        agent_id: "another-agent",
        organization_id: "another-organization",
        user_id: "another-user",
        permissions: ["admin"],
        title: "Dispatch",
        resource: {
          kind: "app",
          id: "scheduler",
          title: "Dispatch",
          agent_id: "another-agent",
          permissions: ["admin"],
        },
        summary: "One unassigned job.",
      }),
    ).toEqual({
      title: "Dispatch",
      resource: { kind: "app", id: "scheduler", title: "Dispatch" },
      summary: "One unassigned job.",
    });
  });
});

describe("assistantPageSnapshot", () => {
  it("stamps a bounded route and explicit registered details at submission", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-09T01:30:00.000Z"));

    expect(
      assistantPageSnapshot("/pl/apps/scheduler?token=private#record", "Dashboard", {
        title: "Dispatch",
        resource: { kind: "app", id: "scheduler" },
        view: "week",
        filters: { status: "unassigned" },
        selected_ids: ["job-17"],
        summary: "One selected job is unassigned.",
        selected_text: "  Keep this selected text.\n",
      }),
    ).toEqual({
      path: "/apps/scheduler",
      title: "Dispatch",
      captured_at: "2026-11-09T01:30:00.000Z",
      resource: { kind: "app", id: "scheduler" },
      view: "week",
      filters: { status: "unassigned" },
      selected_ids: ["job-17"],
      summary: "One selected job is unassigned.",
      selected_text: "  Keep this selected text.\n",
    });
  });

  it("detaches nested state so later page changes cannot rewrite the submitted question", () => {
    const details = {
      resource: { kind: "app", id: "scheduler", title: "Dispatch" },
      filters: { status: "unassigned" },
      selected_ids: ["job-17"],
    };
    const snapshot = assistantPageSnapshot("/apps/scheduler", "Dispatch", details);

    details.resource.title = "Changed";
    details.filters.status = "complete";
    details.selected_ids.push("job-18");

    expect(snapshot.resource).toEqual({ kind: "app", id: "scheduler", title: "Dispatch" });
    expect(snapshot.filters).toEqual({ status: "unassigned" });
    expect(snapshot.selected_ids).toEqual(["job-17"]);
    expect(snapshot.resource).not.toBe(details.resource);
    expect(snapshot.filters).not.toBe(details.filters);
    expect(snapshot.selected_ids).not.toBe(details.selected_ids);
  });

  it("does not invent summary or selected text from document and form contents", () => {
    document.body.innerHTML =
      '<p>Private page contents</p><input type="password" value="private-form-value">';

    const snapshot = assistantPageSnapshot("/apps/scheduler?secret=private-query", "Dispatch");

    expect(snapshot).toEqual({
      path: "/apps/scheduler",
      title: "Dispatch",
      captured_at: expect.any(String),
    });
    expect(JSON.stringify(snapshot)).not.toContain("private");
  });

  it("bounds document titles and the route used when no title is available", () => {
    expect(assistantPageSnapshot("/apps/scheduler", "t".repeat(241)).title).toBe("t".repeat(240));
    const path = "/" + "a".repeat(300);
    const snapshot = assistantPageSnapshot(path, " ");
    expect(snapshot.title).toBe(path.slice(0, 240));
    expect(snapshot.path).toBe(path);
  });
});
