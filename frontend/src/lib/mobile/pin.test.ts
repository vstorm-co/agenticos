import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { agentIcon, ICON_SIZE, pinToHomeScreen, type PinnableAgent } from "./pin";

const AGENT: PinnableAgent = {
  id: "00000000-0000-4000-8000-000000000001",
  name: "Support",
  slug: "support",
  hasAvatar: false,
  colorSlot: 3,
};

const drawn = vi.hoisted(() => ({ calls: [] as unknown[][], sources: [] as string[] }));

/** A canvas that records what is drawn on it, and an image that loads whatever it is given. */
function fakeCanvas(
  context: object | null = { drawImage: (...args: unknown[]) => drawn.calls.push(args) },
) {
  const create = document.createElement.bind(document);
  vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
    if (tag !== "canvas") return create(tag);
    return {
      width: 0,
      height: 0,
      getContext: () => context,
      toDataURL: () => "data:image/png;base64,iVBORw0KGgo=",
    } as unknown as HTMLCanvasElement;
  });
}

/** The avatar route's answer: jsdom's `Response` cannot read a `Blob` back. */
function picture(status: number) {
  return { ok: status === 200, status, blob: async () => new Blob(["png"]) };
}

class LoadingImage {
  width = 400;
  height = 300;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  set src(value: string) {
    drawn.sources.push(value);
    setTimeout(() => (value.includes("broken") ? this.onerror?.() : this.onload?.()));
  }
  get src() {
    return drawn.sources.at(-1) ?? "";
  }
}

beforeEach(() => {
  drawn.calls = [];
  drawn.sources = [];
  vi.stubGlobal("Image", LoadingImage);
});

afterEach(() => {
  delete window.__TAURI__;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("agentIcon", () => {
  it("draws a generated face in the middle of its own colour, clear of the launcher's mask", async () => {
    fakeCanvas();
    await expect(agentIcon(AGENT)).resolves.toBe("iVBORw0KGgo=");

    expect(drawn.sources).toHaveLength(2);
    expect(drawn.sources.every((src) => src.startsWith("data:image/svg+xml"))).toBe(true);
    expect(drawn.calls[0]!.slice(1)).toEqual([0, 0, ICON_SIZE, ICON_SIZE]);
    expect(drawn.calls[1]!.slice(1)).toEqual([72, 72, 288, 288]);
  });

  it("fills the square with an uploaded picture, cut to its middle", async () => {
    fakeCanvas();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => picture(200)),
    );
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:face", revokeObjectURL: vi.fn() }),
    );

    await agentIcon({ ...AGENT, hasAvatar: true });

    expect(fetch).toHaveBeenCalledWith(`/api/agents/${AGENT.id}/avatar`);
    expect(drawn.calls[0]!.slice(1)).toEqual([50, 0, 300, 300, 0, 0, ICON_SIZE, ICON_SIZE]);
  });

  it("fails rather than pinning a blank icon", async () => {
    fakeCanvas(null);
    await expect(agentIcon(AGENT)).rejects.toThrow("no canvas");

    fakeCanvas();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => picture(404)),
    );
    await expect(agentIcon({ ...AGENT, hasAvatar: true })).rejects.toThrow("404");

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => picture(200)),
    );
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:broken" }));
    await expect(agentIcon({ ...AGENT, hasAvatar: true })).rejects.toThrow("could not draw");
  });
});

describe("pinToHomeScreen", () => {
  it("hands the app the agent and its face, and says whether the launcher pinned it", async () => {
    fakeCanvas();
    const invoke = vi.fn(async () => ({ pinned: true }));
    window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };

    await expect(pinToHomeScreen(AGENT)).resolves.toBe(true);
    expect(invoke).toHaveBeenCalledWith("pin_shortcut", {
      shortcut: { id: AGENT.id, name: "Support", icon: "iVBORw0KGgo=" },
    });

    invoke.mockResolvedValue({ pinned: false });
    await expect(pinToHomeScreen(AGENT)).resolves.toBe(false);
  });

  it("refuses an answer it cannot read", async () => {
    fakeCanvas();
    for (const answer of [null, {}, { pinned: "yes" }]) {
      window.__TAURI__ = {
        core: { invoke: vi.fn(async () => answer) },
        event: { listen: vi.fn() },
      };
      await expect(pinToHomeScreen(AGENT)).rejects.toThrow("malformed");
    }
  });
});
