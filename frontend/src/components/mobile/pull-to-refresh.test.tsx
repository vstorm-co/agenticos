import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PULL_THRESHOLD, PullToRefresh } from "./pull-to-refresh";

const haptic = vi.hoisted(() => vi.fn());
const motionPreference = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => motionPreference.reduced }));
vi.mock("@/lib/mobile/haptics", () => ({ haptic }));

const PHONE = { platform: "android", version: "0.1.0", window: "main", vibrancy: false };

let client: QueryClient;

/** The console's scroller with a page in it, and the pull beside it. */
function page() {
  render(
    <QueryClientProvider client={client}>
      <main id="main">
        <div data-testid="inner">
          <p>Runs</p>
        </div>
      </main>
      <PullToRefresh />
    </QueryClientProvider>,
  );
  return screen.getByText("Runs");
}

/** A finger down at y = 0, then to each y given, then lifted. */
function pull(target: Element, ys: number[]) {
  fireEvent.touchStart(target, { touches: [{ clientX: 0, clientY: 0 }] });
  for (const y of ys) fireEvent.touchMove(target, { touches: [{ clientX: 0, clientY: y }] });
  fireEvent.touchEnd(target, { touches: [] });
}

beforeEach(() => {
  client = new QueryClient();
  haptic.mockClear();
  motionPreference.reduced = false;
  window.__AGENTICOS_SHELL__ = PHONE;
});

afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PullToRefresh", () => {
  it("reads what is on screen again when pulled past the point, with a tap at it", async () => {
    let finish!: () => void;
    const refetch = vi
      .spyOn(client, "refetchQueries")
      .mockReturnValue(new Promise<void>((resolve) => (finish = resolve)));
    const target = page();

    fireEvent.touchStart(target, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(target, { touches: [{ clientX: 0, clientY: 40 }] });
    expect(screen.getByTestId("pull-to-refresh")).toBeInTheDocument();
    fireEvent.touchMove(target, { touches: [{ clientX: 0, clientY: PULL_THRESHOLD * 2 + 10 }] });
    expect(haptic).toHaveBeenCalledWith("threshold");
    fireEvent.touchEnd(target, { touches: [] });

    expect(refetch).toHaveBeenCalledWith({ type: "active" });
    expect(screen.getByTestId("pull-to-refresh")).toBeInTheDocument();
    await act(async () => finish());
    await waitFor(() => expect(screen.queryByTestId("pull-to-refresh")).toBeNull());
  });

  it("springs back without refreshing short of the point", async () => {
    const refetch = vi.spyOn(client, "refetchQueries");
    const target = page();
    pull(target, [PULL_THRESHOLD * 2 + 10, PULL_THRESHOLD]);

    expect(refetch).not.toHaveBeenCalled();
    expect(haptic).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByTestId("pull-to-refresh")).toBeNull());
  });

  it("ignores a page scrolled down, an upward swipe and a second finger", () => {
    const refetch = vi.spyOn(client, "refetchQueries");
    const target = page();

    pull(target, [-50]);
    fireEvent.touchStart(target, {
      touches: [
        { clientX: 0, clientY: 0 },
        { clientX: 10, clientY: 0 },
      ],
    });
    fireEvent.touchMove(target, { touches: [{ clientX: 0, clientY: 300 }] });
    fireEvent.touchEnd(target, { touches: [] });

    screen.getByTestId("inner").scrollTop = 120;
    pull(target, [300]);
    screen.getByTestId("inner").scrollTop = 0;
    document.getElementById("main")!.scrollTop = 80;
    pull(target, [300]);

    expect(refetch).not.toHaveBeenCalled();
  });

  it("does not refresh when the operating system cancels an armed pull", async () => {
    const refetch = vi.spyOn(client, "refetchQueries");
    const target = page();
    fireEvent.touchStart(target, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(target, { touches: [{ clientX: 0, clientY: 300 }] });
    expect(screen.getByTestId("pull-to-refresh")).toBeInTheDocument();
    fireEvent.touchCancel(target, { touches: [] });
    await waitFor(() => expect(screen.queryByTestId("pull-to-refresh")).toBeNull());
    fireEvent.touchEnd(target, { touches: [] });
    expect(refetch).not.toHaveBeenCalled();
  });

  it("shows nothing for a tap or a sideways swipe", async () => {
    const refetch = vi.spyOn(client, "refetchQueries");
    const target = page();

    fireEvent.touchStart(target, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(target, { touches: [{ clientX: 3, clientY: 4 }] });
    await waitFor(() => expect(screen.queryByTestId("pull-to-refresh")).toBeNull());
    fireEvent.touchMove(target, { touches: [{ clientX: 120, clientY: 20 }] });
    fireEvent.touchMove(target, { touches: [{ clientX: 120, clientY: 300 }] });
    await waitFor(() => expect(screen.queryByTestId("pull-to-refresh")).toBeNull());
    fireEvent.touchEnd(target, { touches: [] });

    expect(refetch).not.toHaveBeenCalled();
  });

  it("is on for the console installed to a touch screen", () => {
    delete window.__AGENTICOS_SHELL__;
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(display-mode: standalone) and (pointer: coarse)",
    }));
    const refetch = vi.spyOn(client, "refetchQueries").mockResolvedValue();
    pull(page(), [300]);

    expect(refetch).toHaveBeenCalled();
  });

  it("settles immediately with reduced motion and cancels when a second finger joins", async () => {
    motionPreference.reduced = true;
    const refetch = vi.spyOn(client, "refetchQueries");
    const target = page();
    fireEvent.touchStart(target, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(target, { touches: [{ clientX: 0, clientY: 180 }] });
    fireEvent.touchMove(target, {
      touches: [
        { clientX: 0, clientY: 180 },
        { clientX: 10, clientY: 180 },
      ],
    });
    fireEvent.touchEnd(target, { touches: [] });
    expect(refetch).not.toHaveBeenCalled();
    expect(screen.queryByTestId("pull-to-refresh")).toBeNull();
    pull(target, [30]);
    expect(screen.queryByTestId("pull-to-refresh")).toBeNull();
  });

  it("does not start another refresh while one is pending or update a page after unmount", async () => {
    let finish!: () => void;
    const refetch = vi.spyOn(client, "refetchQueries").mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const target = page();
    pull(target, [300]);
    pull(target, [300]);
    expect(refetch).toHaveBeenCalledTimes(1);
    cleanup();
    await act(async () => finish());
    expect(screen.queryByTestId("pull-to-refresh")).toBeNull();
  });

  it("waits for the console scroller to exist", () => {
    const { container } = render(
      <QueryClientProvider client={client}>
        <PullToRefresh />
      </QueryClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("is off in a browser and on the desktop", () => {
    delete window.__AGENTICOS_SHELL__;
    const refetch = vi.spyOn(client, "refetchQueries");
    pull(page(), [300]);

    expect(refetch).not.toHaveBeenCalled();
  });
});
