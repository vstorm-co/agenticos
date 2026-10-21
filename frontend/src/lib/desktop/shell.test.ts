import { afterEach, describe, expect, it, vi } from "vitest";

import {
  invokeShell,
  isDesktopShell,
  isMobileShell,
  listenShell,
  parseShellInfo,
  readShellInfo,
  reportShellFailure,
  ShellError,
} from "./shell";

const MAC = { platform: "macos", version: "0.2.0", window: "main", vibrancy: true };

function fakeTauri(
  invoke: (...args: unknown[]) => unknown,
  listen?: (...args: unknown[]) => unknown,
) {
  window.__TAURI__ = {
    core: { invoke },
    event: { listen: listen ?? (async () => () => {}) },
  };
}

afterEach(() => {
  delete window.__TAURI__;
  delete window.__AGENTICOS_SHELL__;
  vi.restoreAllMocks();
});

describe("parseShellInfo", () => {
  it("reads the shell's announcement", () => {
    expect(parseShellInfo(MAC)).toEqual(MAC);
  });

  it("answers null for anything that is not one, rather than trusting a type", () => {
    expect(parseShellInfo(undefined)).toBeNull();
    expect(parseShellInfo([])).toBeNull();
    expect(parseShellInfo({ ...MAC, platform: "beos" })).toBeNull();
    expect(parseShellInfo({ ...MAC, window: "devtools" })).toBeNull();
    expect(parseShellInfo({ ...MAC, version: 2 })).toBeNull();
    expect(parseShellInfo({ ...MAC, vibrancy: "yes" })).toBeNull();
  });
});

describe("isDesktopShell", () => {
  it("is the desktop app on a computer, and not the phone app or a browser", () => {
    expect(isDesktopShell(parseShellInfo(MAC))).toBe(true);
    expect(isDesktopShell(parseShellInfo({ ...MAC, platform: "ios" }))).toBe(false);
    expect(isDesktopShell(parseShellInfo({ ...MAC, platform: "android" }))).toBe(false);
    expect(isDesktopShell(null)).toBe(false);
  });
});

describe("isMobileShell", () => {
  it("is the phone app, and not the desktop app or a browser", () => {
    expect(isMobileShell(parseShellInfo({ ...MAC, platform: "ios" }))).toBe(true);
    expect(isMobileShell(parseShellInfo({ ...MAC, platform: "android" }))).toBe(true);
    expect(isMobileShell(parseShellInfo(MAC))).toBe(false);
    expect(isMobileShell(null)).toBe(false);
  });
});

describe("readShellInfo", () => {
  it("is null in a browser and the announcement inside the app", () => {
    expect(readShellInfo()).toBeNull();
    window.__AGENTICOS_SHELL__ = MAC;
    expect(readShellInfo()).toEqual(MAC);
  });
});

describe("invokeShell", () => {
  it("passes the command and its arguments through and answers what the shell answered", async () => {
    const invoke = vi.fn(async () => 42);
    fakeTauri(invoke);
    await expect(invokeShell("set_badge", { count: 3 })).resolves.toBe(42);
    expect(invoke).toHaveBeenCalledWith("set_badge", { count: 3 });
  });

  it("turns the shell's refusal into a ShellError carrying its reason", async () => {
    fakeTauri(async () => Promise.reject("Alt+Space could not be bound"));
    const error = await invokeShell("set_shortcut").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ShellError);
    expect((error as ShellError).failure).toBe("refused");
    expect((error as ShellError).message).toContain("Alt+Space could not be bound");
  });

  it("keeps the message of an Error and stringifies anything else", async () => {
    fakeTauri(async () => Promise.reject(new Error("boom")));
    await expect(invokeShell("x")).rejects.toThrow("refused: boom");
    fakeTauri(async () => Promise.reject(7));
    await expect(invokeShell("x")).rejects.toThrow("refused: 7");
  });

  it("says there is no shell in a browser, or one without the API", async () => {
    await expect(invokeShell("x")).rejects.toMatchObject({ failure: "unavailable" });
    window.__TAURI__ = { core: {}, event: {} };
    await expect(invokeShell("x")).rejects.toMatchObject({ failure: "unavailable" });
    window.__TAURI__ = { core: 1, event: {} };
    await expect(invokeShell("x")).rejects.toMatchObject({ failure: "unavailable" });
  });
});

describe("listenShell", () => {
  it("hands the handler each event's payload and resolves to the unlisten", async () => {
    const stop = vi.fn();
    let emit: (event: { payload: unknown }) => void = () => {};
    fakeTauri(
      async () => null,
      async (_name: unknown, handler: unknown) => {
        emit = handler as typeof emit;
        return stop;
      },
    );
    const handler = vi.fn();
    const unlisten = await listenShell("desktop:say", handler);
    emit({ payload: "hello" });
    unlisten();
    expect(handler).toHaveBeenCalledWith("hello");
    expect(stop).toHaveBeenCalled();
  });

  it("refuses an unlisten that is not a function, and a page with no shell", async () => {
    fakeTauri(
      async () => null,
      async () => "nope",
    );
    await expect(listenShell("x", () => {})).rejects.toMatchObject({ failure: "malformed" });
    delete window.__TAURI__;
    await expect(listenShell("x", () => {})).rejects.toMatchObject({ failure: "unavailable" });
  });
});

describe("reportShellFailure", () => {
  it("says it on the console rather than swallowing it", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const error = new Error("x");
    reportShellFailure("could not set the badge", error);
    expect(warn).toHaveBeenCalledWith("desktop", "could not set the badge", error);
  });
});
