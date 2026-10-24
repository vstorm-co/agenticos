import { beforeEach, describe, expect, it, vi } from "vitest";

import * as commands from "./commands";
import {
  parseApprovalDecision,
  parseBlobbySettings,
  parseDesktopState,
  type BlobbySettings,
  type DesktopState,
} from "./commands";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("./shell")>()),
  invokeShell: invoke,
}));

const BLOBBY: BlobbySettings = {
  enabled: true,
  character: { kind: "cast", id: "pebble" },
  chatter: "normal",
  activity: true,
  roams: false,
  size: 1.2,
  position: { x: 10, y: 20 },
};

const SUPPORT = { id: "00000000-0000-4000-8000-000000000001", name: "Support" };

const STATE: DesktopState = {
  appearance: { look: "glass", mode: "dark" },
  blobby: BLOBBY,
  pinned: [SUPPORT],
  shortcuts: [{ action: "quick_ask", accelerator: "Alt+Space", problem: null }],
  window: { keep_running: true, badge: false, launch_at_login: true },
};

beforeEach(() => invoke.mockReset());

describe("parseDesktopState", () => {
  it("reads the state the shell sends", () => {
    expect(parseDesktopState(STATE)).toEqual(STATE);
  });

  it("reads no pinned agents from a shell older than pinning", () => {
    const { pinned: _pinned, ...older } = STATE;
    expect(parseDesktopState(older).pinned).toEqual([]);
    expect(() => parseDesktopState({ ...STATE, pinned: {} })).toThrow(
      "malformed: the pinned agents",
    );
    expect(() => parseDesktopState({ ...STATE, pinned: [{ id: 1, name: "x" }] })).toThrow(
      "malformed",
    );
  });

  it("leaves out a shortcut a newer shell knows and this console does not", () => {
    const state = parseDesktopState({
      ...STATE,
      shortcuts: [
        ...STATE.shortcuts,
        { action: "summon_blobby", accelerator: null, problem: null },
      ],
    });
    expect(state.shortcuts.map((s) => s.action)).toEqual(["quick_ask"]);
  });

  it("refuses a shape it does not know rather than drawing a page from undefined", () => {
    expect(() => parseDesktopState(null)).toThrow("malformed");
    expect(() => parseDesktopState({ ...STATE, shortcuts: {} })).toThrow("malformed: shortcuts");
    expect(() =>
      parseDesktopState({ ...STATE, appearance: { look: "neon", mode: "dark" } }),
    ).toThrow("malformed: look");
    expect(() =>
      parseDesktopState({ ...STATE, appearance: { look: "glass", mode: "dim" } }),
    ).toThrow("malformed: mode");
    expect(() => parseDesktopState({ ...STATE, window: { ...STATE.window, badge: 1 } })).toThrow(
      "malformed: badge",
    );
    expect(() =>
      parseDesktopState({
        ...STATE,
        shortcuts: [{ action: "quick_ask", accelerator: 3, problem: null }],
      }),
    ).toThrow("malformed: accelerator");
  });
});

describe("parseBlobbySettings", () => {
  it("takes a shell from before blobby could be resized as its natural size", () => {
    const { size: _omitted, ...older } = BLOBBY;
    expect(parseBlobbySettings(older).size).toBe(1);
  });

  it("reads every kind of character and a position that is not there yet", () => {
    const agent = {
      kind: "agent",
      agent_id: "a1",
      slug: "support",
      name: "Support",
      color_slot: 3,
    };
    const custom = { kind: "custom", seed: "kacper", color_slot: null };
    expect(parseBlobbySettings({ ...BLOBBY, character: agent, position: null }).character).toEqual(
      agent,
    );
    expect(parseBlobbySettings({ ...BLOBBY, character: custom }).character).toEqual(custom);
    const { position: _omitted, ...withoutPosition } = BLOBBY;
    expect(parseBlobbySettings(withoutPosition).position).toBeNull();
  });

  it("refuses a character, a chatter or a position it does not know", () => {
    expect(() => parseBlobbySettings({ ...BLOBBY, character: { kind: "ghost" } })).toThrow(
      "malformed: character",
    );
    expect(() => parseBlobbySettings({ ...BLOBBY, chatter: "loud" })).toThrow("malformed: chatter");
    expect(() => parseBlobbySettings({ ...BLOBBY, position: { x: "1", y: 2 } })).toThrow(
      "malformed: x",
    );
    expect(() =>
      parseBlobbySettings({
        ...BLOBBY,
        character: { kind: "custom", seed: "x", color_slot: Infinity },
      }),
    ).toThrow("malformed: color_slot");
  });
});

describe("parseApprovalDecision", () => {
  it("reads a decision taken on a notification", () => {
    expect(parseApprovalDecision({ approval_id: "ap1", approved: false })).toEqual({
      approval_id: "ap1",
      approved: false,
    });
    expect(() => parseApprovalDecision({ approval_id: "ap1" })).toThrow("malformed: approved");
  });
});

describe("the commands", () => {
  it("each sends its command with its arguments", async () => {
    invoke.mockResolvedValue(STATE);
    await expect(commands.getDesktopState()).resolves.toEqual(STATE);
    invoke.mockResolvedValue(null);
    await commands.setAppearance(STATE.appearance);
    await commands.setBlobby(BLOBBY);
    await commands.setWindowPreferences(STATE.window);
    await commands.notify({ kind: "inbox", title: "t", body: "b", path: "/runs" });
    await commands.setBadge(3.7);
    await commands.setBadge(-2);
    await commands.openInConsole("/chat");
    await commands.openChat();
    await commands.showConsole();
    await commands.saveBlobbyPosition(1, 2);
    await commands.showBlobbyMenu();
    await commands.resizeBlobby(9);
    await commands.resizeQuickAsk(300);
    await commands.hideQuickAsk();
    await commands.finishOnboarding();

    expect(invoke.mock.calls).toEqual([
      ["desktop_state"],
      ["set_appearance", { appearance: STATE.appearance }],
      ["set_blobby", { blobby: BLOBBY }],
      ["set_window_preferences", { preferences: STATE.window }],
      ["notify", { notice: { kind: "inbox", title: "t", body: "b", path: "/runs" } }],
      ["set_badge", { count: 3 }],
      ["set_badge", { count: 0 }],
      ["open_in_console", { path: "/chat" }],
      ["open_chat"],
      ["show_console"],
      ["save_blobby_position", { x: 1, y: 2 }],
      ["blobby_menu"],
      ["resize_blobby", { size: 1.6 }],
      ["resize_quick_ask", { height: 300 }],
      ["hide_quick_ask"],
      ["finish_onboarding"],
    ]);
  });

  it("pins and unpins an agent, answering with the list as it now stands", async () => {
    invoke.mockResolvedValue([SUPPORT]);
    await expect(commands.pinAgent(SUPPORT)).resolves.toEqual([SUPPORT]);
    expect(invoke).toHaveBeenLastCalledWith("pin_agent", { agent: SUPPORT });
    invoke.mockResolvedValue([]);
    await expect(commands.unpinAgent(SUPPORT.id)).resolves.toEqual([]);
    expect(invoke).toHaveBeenLastCalledWith("unpin_agent", { id: SUPPORT.id });
  });

  it("answers with what the shell bound, and refuses an answer that is not a binding", async () => {
    invoke.mockResolvedValue("Alt+K");
    await expect(commands.setShortcut("quick_ask", "Alt+K")).resolves.toBe("Alt+K");
    expect(invoke).toHaveBeenCalledWith("set_shortcut", {
      action: "quick_ask",
      accelerator: "Alt+K",
    });
    invoke.mockResolvedValue(null);
    await expect(commands.setShortcut("quick_ask", null)).resolves.toBeNull();
    invoke.mockResolvedValue(5);
    await expect(commands.setShortcut("quick_ask", "Alt+K")).rejects.toThrow("malformed: binding");
  });
});

describe("local files and service grants", () => {
  it("decodes native file results and refuses malformed data", async () => {
    invoke.mockResolvedValue([{ path: "a.txt", size: 2, is_dir: false, modified: null }]);
    await expect(commands.listLocalFiles("/work")).resolves.toEqual([
      { path: "a.txt", size: 2, is_dir: false, modified: null },
    ]);
    invoke.mockResolvedValue({});
    await expect(commands.listLocalFiles("/work")).rejects.toThrow("malformed");
    invoke.mockResolvedValue("aGk=");
    await expect(commands.readLocalFile("/work", "a.txt")).resolves.toEqual(
      new Uint8Array([104, 105]),
    );
    invoke.mockResolvedValue(null);
    await expect(commands.readLocalFile("/work", "a.txt")).rejects.toThrow("malformed");
  });
  it("validates native services rather than trusting the IPC result", async () => {
    const service = {
      id: "mine",
      name: "My model",
      kind: "model" as const,
      model: "installed",
      endpoint: "http://127.0.0.1:11434/v1",
    };
    invoke.mockResolvedValue([service]);
    await expect(commands.getLocalServices()).resolves.toEqual([service]);
    await expect(commands.saveLocalService(service)).resolves.toEqual([service]);
    await expect(commands.removeLocalService("mine")).resolves.toEqual([service]);
    invoke.mockResolvedValue([{ ...service, kind: "unknown" }]);
    await expect(commands.getLocalServices()).rejects.toThrow("malformed");
    invoke.mockResolvedValue(null);
    await expect(commands.getLocalServices()).rejects.toThrow("malformed");
  });
});

describe("paired device and folder grants", () => {
  it("validates native device state and sends only the pairing code", async () => {
    invoke.mockResolvedValue({ linked: true, connected: false });
    expect(await commands.getDeviceStatus()).toEqual({ linked: true, connected: false });
    await commands.linkDevice("once");
    expect(invoke).toHaveBeenLastCalledWith("device_link", { code: "once" });
    await commands.unlinkDevice();
    expect(invoke).toHaveBeenLastCalledWith("device_unlink");
    expect(() => commands.parseDeviceStatus({ linked: "yes", connected: true })).toThrow();
  });
  it("keeps native folder modes and cancellation distinct from an empty grant", async () => {
    const grant = { path: "/approved", mode: "read_only" };
    invoke.mockResolvedValue({ grants: [grant], modes: ["read_only", "future_mode"] });
    expect(await commands.getLocalState()).toEqual({ grants: [grant], modes: ["read_only"] });
    await commands.revokeLocalFolder(grant.path);
    expect(invoke).toHaveBeenLastCalledWith("local_revoke", { path: grant.path });
    invoke.mockResolvedValue(grant);
    expect(await commands.pickLocalFolder("read_only")).toEqual(grant);
    invoke.mockResolvedValue(null);
    expect(await commands.pickLocalFolder("read_only")).toBeNull();
    expect(() => commands.parseLocalState({})).toThrow();
    expect(() =>
      commands.parseLocalState({ grants: [{ path: "/bad", mode: "unknown" }], modes: [] }),
    ).toThrow();
  });
});
