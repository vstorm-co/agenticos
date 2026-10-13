import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserPanel } from "./browser-panel";
import type { Browse } from "@/lib/browse";
import { useAuthStore } from "@/stores";
import {
  DEFAULT_PANEL_WIDTH,
  MAX_PANEL_WIDTH,
  MIN_PANEL_WIDTH,
  useBrowserPanelStore,
} from "@/stores/browser-panel-store";

const live = vi.hoisted(() => ({
  value: {
    browse: null as Browse | null,
    task: "",
    canControl: false,
    status: "connecting" as string,
    send: vi.fn(),
  },
  calls: [] as [string, string, boolean | undefined][],
}));

vi.mock("@/hooks/use-live-browse", () => ({
  useLiveBrowse: (runId: string, callId: string, enabled?: boolean) => {
    live.calls.push([runId, callId, enabled]);
    return live.value;
  },
}));

function browse(overrides: Partial<Browse> = {}): Browse {
  return {
    callId: "c1",
    runId: "run-1",
    goal: "find the price",
    maxSteps: 25,
    url: "https://example.test/pricing",
    title: "Pricing",
    steps: [],
    image: null,
    imageStep: -1,
    outcome: null,
    detail: null,
    ...overrides,
  };
}

/** Whether the screen is wide enough for the panel to dock. */
function wide(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches }) as never;
}

beforeEach(() => {
  live.value = { browse: null, task: "", canControl: false, status: "connecting", send: vi.fn() };
  live.calls = [];
  wide(true);
  useAuthStore.setState({ user: { id: "u1", full_name: "Ada", email: "ada@acme.test" } as never });
  useBrowserPanelStore.setState({ openCallId: null, mode: "panel", width: DEFAULT_PANEL_WIDTH });
});

describe("BrowserPanel - the agent's browser beside the conversation", () => {
  it("draws nothing when nothing has browsed", () => {
    const { container } = render(<BrowserPanel browses={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("opens by itself when a browse starts, on a screen wide enough to dock it", () => {
    render(<BrowserPanel browses={[browse()]} />);

    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
    expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
  });

  it("opens once per browse - closing it is a decision the next frame does not undo", () => {
    const { rerender } = render(<BrowserPanel browses={[browse()]} />);
    useBrowserPanelStore.getState().close();

    rerender(<BrowserPanel browses={[browse({ title: "Pricing - step 2" })]} />);

    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
  });

  it("leaves a finished browse, a phone and a small scope to the line in the transcript", () => {
    const { unmount } = render(<BrowserPanel browses={[browse({ outcome: "done" })]} />);
    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
    unmount();

    wide(false);
    render(<BrowserPanel browses={[browse({ callId: "c2" })]} />);
    expect(useBrowserPanelStore.getState().openCallId).toBeNull();

    wide(true);
    render(<BrowserPanel browses={[browse({ callId: "c3" })]} docked={false} />);
    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
  });

  it("does not take the panel from a browse somebody already has open", () => {
    useBrowserPanelStore.setState({ openCallId: "c1" });
    render(<BrowserPanel browses={[browse({ outcome: "done" }), browse({ callId: "c2" })]} />);
    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
  });

  it("closes on Escape, except while a person holds the page", () => {
    live.value = { ...live.value, browse: browse({ heldBy: "Ada" }), status: "live" };
    useBrowserPanelStore.setState({ openCallId: "c1" });
    const { rerender } = render(<BrowserPanel browses={[browse()]} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");

    live.value = { ...live.value, browse: null };
    rerender(<BrowserPanel browses={[browse()]} />);
    fireEvent.keyDown(window, { key: "Enter" });
    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
  });

  it("opens the live view only for a running browse with a run, and drives through it", async () => {
    live.value = {
      ...live.value,
      browse: browse({ title: "Live copy" }),
      canControl: true,
      status: "live",
    };
    useBrowserPanelStore.setState({ openCallId: "c1" });
    render(<BrowserPanel browses={[browse()]} />);

    expect(live.calls.at(-1)).toEqual(["run-1", "c1", true]);
    expect(screen.getByRole("heading", { name: "Live copy" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Take over/ }));
    expect(live.value.send).toHaveBeenCalledWith({ type: "take_over" });
  });

  it("keeps to the stream once the browse is over, or while the live view is another browse's", () => {
    live.value = {
      ...live.value,
      browse: browse({ callId: "other", title: "Other" }),
      status: "live",
    };
    useBrowserPanelStore.setState({ openCallId: "c1" });
    const { rerender } = render(<BrowserPanel browses={[browse()]} />);
    expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Take over/ })).toBeNull();

    live.value = { ...live.value, browse: browse({ title: "Live copy" }) };
    rerender(<BrowserPanel browses={[browse({ outcome: "done", runId: null })]} />);
    expect(live.calls.at(-1)).toEqual(["", "c1", false]);
    expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open in a new tab" })).toBeNull();
  });

  it("links the browse's own page, and maximises and restores", async () => {
    useBrowserPanelStore.setState({ openCallId: "c1" });
    render(<BrowserPanel browses={[browse()]} />);
    expect(screen.getByRole("link", { name: "Open in a new tab" })).toHaveAttribute(
      "href",
      "/browse/run-1/c1",
    );

    await userEvent.click(screen.getByRole("button", { name: "Maximize" }));
    expect(useBrowserPanelStore.getState().mode).toBe("full");
    expect(screen.queryByRole("slider")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Back to the side panel" }));
    expect(useBrowserPanelStore.getState().mode).toBe("panel");
  });

  it("takes the screen without a maximise button in a small scope", () => {
    useBrowserPanelStore.setState({ openCallId: "c1" });
    render(<BrowserPanel browses={[browse()]} docked={false} />);

    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByRole("button", { name: "Maximize" })).toBeNull();
  });

  it("is resized by dragging its edge or with the arrow keys, within bounds", () => {
    useBrowserPanelStore.setState({ openCallId: "c1" });
    render(<BrowserPanel browses={[browse()]} />);
    const handle = screen.getByRole("slider", { name: "Resize the browser view" });

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(useBrowserPanelStore.getState().width).toBe(DEFAULT_PANEL_WIDTH + 40);
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(useBrowserPanelStore.getState().width).toBe(DEFAULT_PANEL_WIDTH - 40);
    fireEvent.keyDown(handle, { key: "Enter" });
    expect(useBrowserPanelStore.getState().width).toBe(DEFAULT_PANEL_WIDTH - 40);

    handle.setPointerCapture = vi.fn();
    fireEvent.pointerDown(handle, { pointerId: 1 });
    fireEvent.pointerMove(handle, { buttons: 0, clientX: 0 });
    expect(useBrowserPanelStore.getState().width).toBe(DEFAULT_PANEL_WIDTH - 40);
    fireEvent.pointerMove(handle, { buttons: 1, clientX: window.innerWidth - 10_000 });
    expect(useBrowserPanelStore.getState().width).toBe(MAX_PANEL_WIDTH);
    fireEvent.pointerMove(handle, { buttons: 1, clientX: window.innerWidth });
    expect(useBrowserPanelStore.getState().width).toBe(MIN_PANEL_WIDTH);
  });
});
