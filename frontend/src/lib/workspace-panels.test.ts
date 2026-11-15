import { describe, expect, it } from "vitest";
import type { Browse } from "./browse";
import type { ChatMessage } from "@/types/chat";
import {
  browseSurfaces,
  browseSurface,
  selectedWorkspaceBrowse,
  workspaceStartReason,
  workspaceWebsite,
  type WorkspaceStartAccess,
} from "./workspace-panels";

const view = (callId: string, more: Partial<Browse> = {}): Browse => ({
  callId,
  runId: "run",
  goal: "",
  maxSteps: null,
  url: null,
  title: null,
  steps: [],
  image: null,
  imageStep: -1,
  outcome: null,
  detail: null,
  ...more,
});

describe("workspace preview identity", () => {
  it("uses real canonical tools even when labels are renamed, ignoring unrelated tools", () => {
    const surfaces = browseSurfaces([
      {
        id: "turn",
        role: "assistant",
        content: "",
        timestamp: new Date(),
        toolCalls: [
          {
            id: "screen",
            name: "renamed",
            tool_id: "computer_screenshot",
            args: {},
            status: "completed",
          },
          { id: "act", name: "computer_act", args: {}, status: "completed" },
          { id: "page", name: "browser_open", args: {}, status: "completed" },
          { id: "search", name: "web_search", args: {}, status: "completed" },
          {
            id: "external",
            name: "computer_screenshot",
            presentation_kind: "generic",
            args: {},
            status: "completed",
          },
        ],
      },
      { id: "text", role: "assistant", content: "", timestamp: new Date() },
    ] satisfies ChatMessage[]);
    expect([...surfaces]).toEqual([
      ["screen", "computer"],
      ["act", "computer"],
      ["page", "browser"],
    ]);
    expect(
      browseSurface(view("screen", { title: "Example Domain", navigable: true }), surfaces),
    ).toBe("computer");
    expect(browseSurface(view("unknown", { title: "Computer" }), surfaces)).toBeNull();
    expect(browseSurface(view("native", { nativeId: "native" }), surfaces)).toBe("browser");
    expect(browseSurface(view("new", { navigable: true }), surfaces)).toBe("browser");
  });

  it("follows only the selected kind and preserves a deliberately selected historical view", () => {
    const old = view("old", { navigable: true, tabId: "a", outcome: "done" });
    const resumed = view("resumed", { navigable: true, tabId: "a", runId: "next" });
    const other = view("other", { navigable: true, tabId: "b" });
    const desktop = view("desktop");
    const surfaces = new Map([["desktop", "computer" as const]]);
    const views = [old, resumed, desktop, other];
    expect(selectedWorkspaceBrowse(views, surfaces, null, null)).toBeNull();
    expect(selectedWorkspaceBrowse(views, surfaces, "computer", null)).toBe(desktop);
    expect(selectedWorkspaceBrowse(views, surfaces, "browser", null)).toBe(other);
    expect(selectedWorkspaceBrowse(views, surfaces, "browser", "old")).toBe(resumed);
    expect(selectedWorkspaceBrowse(views, surfaces, "computer", "other")).toBeNull();
    expect(selectedWorkspaceBrowse(views, surfaces, "browser", "gone")).toBeNull();
    expect(selectedWorkspaceBrowse([], surfaces, "computer", null)).toBeNull();
    const legacy = view("legacy", { tabId: "old-shape" });
    expect(selectedWorkspaceBrowse([legacy], surfaces, "browser", "legacy")).toBe(legacy);
    expect(selectedWorkspaceBrowse([desktop], surfaces, "computer", "desktop")).toBe(desktop);
    const native = view("native", { nativeId: "personal-browser" });
    expect(selectedWorkspaceBrowse([native], surfaces, "browser", null)).toBeNull();
    expect(selectedWorkspaceBrowse([native], surfaces, "browser", "native")).toBe(native);
    const hosted = view("hosted", { navigable: true, tabId: "shared-tab-id" });
    const nativeCollision = { ...native, tabId: hosted.tabId };
    expect(selectedWorkspaceBrowse([hosted, nativeCollision], surfaces, "browser", null)).toBe(
      hosted,
    );
  });
});

const ready: WorkspaceStartAccess = {
  teamRoom: false,
  hasAgent: true,
  hostedCapabilities: ["browser_use", "computer_use"],
  canRun: true,
  readOnly: false,
  localSelected: false,
  busy: false,
  connected: true,
};

describe("hosted start availability", () => {
  it.each([
    [{ teamRoom: true, hasAgent: false, canRun: false }, "roomComposer"],
    [{ teamRoom: true, readOnly: true, hasAgent: false, canRun: false }, "readOnly"],
    [{ hasAgent: false }, "chooseAgent"],
    [{ canRun: false }, "readOnly"],
    [{ readOnly: true }, "readOnly"],
    [{ hostedCapabilities: null }, "unknown"],
    [{ hostedCapabilities: [] }, "browserUnavailable"],
    [{ localSelected: true }, "localSelected"],
    [{ busy: true }, "busy"],
    [{ connected: false }, "disconnected"],
  ] as const)("refuses %j with a useful reason", (changes, reason) => {
    expect(workspaceStartReason({ ...ready, ...changes }, "browser")).toBe(reason);
  });
  it("requires the chosen hosted capability and allows only an otherwise ready chat", () => {
    expect(
      workspaceStartReason({ ...ready, hostedCapabilities: ["browser_use"] }, "computer"),
    ).toBe("computerUnavailable");
    expect(workspaceStartReason(ready, "computer")).toBeNull();
    expect(workspaceStartReason(ready, "browser")).toBeNull();
  });
});

describe("deliberate browser destinations", () => {
  it.each([
    "",
    "example.com",
    "not a URL",
    "about:blank",
    "file:///tmp/file",
    "javascript:alert(1)",
    "https://name@example.com",
    "https://:secret@example.com",
  ])("rejects %s", (url) => {
    expect(workspaceWebsite(url)).toBeNull();
  });
  it.each([
    [" https://example.com/path?q=one ", "https://example.com/path?q=one"],
    ["http://example.com", "http://example.com/"],
  ])("normalizes %s without fetching it", (url, expected) => {
    expect(workspaceWebsite(url)).toBe(expected);
  });
});
