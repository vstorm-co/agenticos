import { useEffect } from "react";
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNativeBrowser } from "./use-native-browser";

const api = vi.hoisted(() => ({ control: vi.fn(), state: vi.fn(), report: vi.fn() }));
vi.mock("@/lib/desktop/browser", () => ({
  controlNativeBrowser: api.control,
  nativeBrowserState: api.state,
}));
vi.mock("@/lib/desktop/shell", () => ({ reportShellFailure: api.report }));
let resize: () => void;
let mutate: () => void;
let browser: ReturnType<typeof useNativeBrowser>;
function View({ id = "tab" }: { id?: string }) {
  const { viewport, state, error, send } = useNativeBrowser(id);
  useEffect(() => {
    browser = { viewport, state, error, send };
  }, [viewport, state, error, send]);
  return (
    <>
      <div ref={viewport} data-testid="viewport" />
      <output>{error}</output>
    </>
  );
}
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}
beforeEach(() => {
  vi.useFakeTimers();
  api.control.mockReset().mockResolvedValue(null);
  api.state
    .mockReset()
    .mockResolvedValue({ url: "https://example.test/", title: "Example", held: false });
  api.report.mockReset();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "MutationObserver",
    class {
      constructor(callback: () => void) {
        mutate = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(
    new DOMRect(10, 60, 900, 600),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("native viewport lifecycle", () => {
  it("mounts native pixels, polls metadata and hides after outstanding work", async () => {
    const view = render(<View />);
    await settle();
    expect(api.control).toHaveBeenCalledWith("tab", "show", {
      mount: expect.any(String),
      bounds: { x: 10, y: 60, width: 900, height: 600 },
    });
    expect(browser.state?.title).toBe("Example");
    act(() => {
      resize();
      resize();
    });
    await settle();
    expect(api.control.mock.calls.filter((call) => call[1] === "show")).toHaveLength(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(api.state).toHaveBeenCalledTimes(2);
    view.unmount();
    resize();
    await settle();
    expect(api.control).toHaveBeenLastCalledWith("tab", "hide", { mount: expect.any(String) });
  });
  it("supports a hook without a mounted viewport", async () => {
    const view = renderHook(() => useNativeBrowser("tab"));
    await settle();
    expect(api.control).not.toHaveBeenCalled();
    view.unmount();
  });
  it("hides while a dialog blocks the page and while the app is hidden", async () => {
    const view = render(<View />);
    await settle();
    const dialog = document.createElement("dialog");
    dialog.open = true;
    document.body.append(dialog);
    act(() => mutate());
    await settle();
    expect(api.control).toHaveBeenLastCalledWith("tab", "hide", { mount: expect.any(String) });
    dialog.remove();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await settle();
    expect(api.control).toHaveBeenLastCalledWith("tab", "hide", { mount: expect.any(String) });
    view.unmount();
    await settle();
  });
  it.each([new DOMRect(0, 0, 0, 100), new DOMRect(0, 0, 100, 0)])(
    "does not mount an empty viewport",
    async (bounds) => {
      vi.mocked(Element.prototype.getBoundingClientRect).mockReturnValue(bounds);
      const view = render(<View />);
      await settle();
      expect(api.control).toHaveBeenCalledWith("tab", "hide", { mount: expect.any(String) });
      view.unmount();
      await settle();
    },
  );
  it.each([new Error("Mount refused"), "Mount refused"])(
    "shows a failed native layout %j",
    async (reason) => {
      api.control.mockRejectedValueOnce(reason);
      const view = render(<View />);
      await settle();
      expect(screen.getByText("Mount refused")).toBeInTheDocument();
      view.unmount();
      await settle();
    },
  );
  it.each([new Error("Device gone"), "Device gone"])(
    "shows state and control refusals %j",
    async (reason) => {
      api.state.mockRejectedValueOnce(reason);
      const view = render(<View />);
      await settle();
      expect(browser.error).toBe("Device gone");
      api.control.mockRejectedValueOnce(reason);
      await act(async () => {
        await browser.send("reload");
      });
      expect(browser.error).toBe("Device gone");
      await act(async () => {
        await browser.send("navigate", "https://example.test/new");
      });
      expect(browser.error).toBeNull();
      expect(api.control).toHaveBeenCalledWith("tab", "navigate", {
        url: "https://example.test/new",
      });
      view.unmount();
      await settle();
    },
  );
  it("does not revive a disposed renderer after a pending poll or layout", async () => {
    let resolveState: ((value: { url: string; title: string; held: boolean }) => void) | undefined;
    let rejectLayout: ((reason: Error) => void) | undefined;
    api.state.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveState = resolve;
      }),
    );
    api.control.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectLayout = reject;
      }),
    );
    const view = render(<View />);
    await settle();
    view.unmount();
    await act(async () => {
      resolveState?.({ url: "x", title: "old", held: false });
      rejectLayout?.(new Error("Closed"));
    });
    await settle();
    expect(api.control).toHaveBeenLastCalledWith("tab", "hide", { mount: expect.any(String) });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(api.state).toHaveBeenCalledTimes(1);
  });
  it("reports cleanup failures and ignores a late failed state probe", async () => {
    let rejectState: ((reason: Error) => void) | undefined;
    api.state.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectState = reject;
      }),
    );
    const view = render(<View />);
    await settle();
    api.control.mockRejectedValueOnce(new Error("Cannot hide"));
    view.unmount();
    await act(async () => {
      rejectState?.(new Error("Closed"));
    });
    await settle();
    expect(api.report).toHaveBeenCalledWith("could not hide the native browser", expect.any(Error));
  });
});

it("does not show a native viewport after it was immediately unmounted", async () => {
  const view = render(<View />);
  view.unmount();
  await settle();
  expect(api.control).not.toHaveBeenCalledWith("tab", "show", expect.anything());
  expect(api.control).toHaveBeenLastCalledWith("tab", "hide", { mount: expect.any(String) });
});

it("closes without querying the destroyed native document", async () => {
  const view = render(<View />);
  await settle();
  api.state.mockClear();
  await act(async () => {
    expect(await browser.send("close")).toBe(true);
  });
  expect(api.state).not.toHaveBeenCalled();
  expect(browser.state).toBeNull();
  view.unmount();
  await settle();
});

it("hides native pixels during a panel drag and restores their new geometry", async () => {
  const view = render(<View />);
  await settle();
  const blocker = document.createElement("div");
  blocker.setAttribute("data-native-browser-blocked", "");
  document.body.append(blocker);
  act(() => mutate());
  await settle();
  expect(api.control).toHaveBeenLastCalledWith("tab", "hide", { mount: expect.any(String) });
  blocker.remove();
  vi.mocked(Element.prototype.getBoundingClientRect).mockReturnValue(
    new DOMRect(500, 60, 700, 600),
  );
  act(() => resize());
  await settle();
  expect(api.control).toHaveBeenLastCalledWith("tab", "show", {
    mount: expect.any(String),
    bounds: { x: 500, y: 60, width: 700, height: 600 },
  });
  view.unmount();
  await settle();
});
