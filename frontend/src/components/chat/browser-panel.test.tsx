import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserPanel } from "./browser-panel";
import type { Browse } from "@/lib/browse";
import { useAuthStore } from "@/stores";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";

vi.mock("@/hooks/use-native-browser", () => ({
  useNativeBrowser: () => ({
    viewport: { current: null },
    state: null,
    error: null,
    send: vi.fn(),
  }),
}));

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

beforeEach(() => {
  live.value = { browse: null, task: "", canControl: false, status: "connecting", send: vi.fn() };
  live.calls = [];
  useAuthStore.setState({ user: { id: "u1", full_name: "Ada", email: "ada@acme.test" } as never });
  useBrowserPanelStore.setState({ openCallId: null });
});

describe("BrowserPanel - a browse beside the chat", () => {
  it("draws nothing when nothing has browsed, or nothing was opened", () => {
    const { container, rerender } = render(<BrowserPanel browses={[]} />);
    expect(container).toBeEmptyDOMElement();

    // Opening is owned by BrowserPanelAutoOpen; this component only renders the selection.
    rerender(<BrowserPanel browses={[browse()]} />);
    expect(container).toBeEmptyDOMElement();
    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
  });

  it("shows the browse somebody opened, by id", () => {
    useBrowserPanelStore.setState({ openCallId: "c2" });
    render(<BrowserPanel browses={[browse(), browse({ callId: "c2", title: "Docs" })]} />);
    expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
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

  it("links the browse's own page, and goes back under the message", async () => {
    useBrowserPanelStore.setState({ openCallId: "c1" });
    render(<BrowserPanel browses={[browse()]} />);
    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    expect(screen.getByRole("menuitem", { name: "Open in a new tab" })).toHaveAttribute(
      "href",
      "/browse/run-1/c1",
    );

    await userEvent.keyboard("{Escape}");
    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Close the browser panel" }));
    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
  });
});

it("shows a native tab only in the owning desktop console", () => {
  useBrowserPanelStore.setState({ openCallId: "c1" });
  const view = render(<BrowserPanel browses={[browse({ nativeId: "native-browser-test" })]} />);
  expect(screen.getByText(/This tab is open in the paired desktop app/)).toBeInTheDocument();
  view.unmount();
});

it("mounts the native renderer in the desktop console", () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "0.2.0",
    window: "main",
    vibrancy: true,
  };
  try {
    useBrowserPanelStore.setState({ openCallId: "c1" });
    const view = render(<BrowserPanel browses={[browse({ nativeId: "native-browser-test" })]} />);
    expect(screen.getByRole("button", { name: "Close tab" })).toBeInTheDocument();
    view.unmount();
  } finally {
    delete window.__AGENTICOS_SHELL__;
  }
});

it("expands and docks the same remote browse without closing it", async () => {
  useBrowserPanelStore.setState({ openCallId: "c1" });
  const view = render(<BrowserPanel browses={[browse()]} />);
  const panel = view.container.querySelector("[data-browser-panel]");
  expect(panel).toHaveAttribute("data-browser-panel", "docked");
  await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Maximize" }));
  expect(panel).toHaveAttribute("data-browser-panel", "fullscreen");
  await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Back beside the chat" }));
  expect(panel).toHaveAttribute("data-browser-panel", "docked");
  expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
});

it("switches pages from the side panel tab strip without keeping a duplicate preview", async () => {
  const tabs = [
    browse({ navigable: true }),
    browse({ callId: "c2", navigable: true, title: "Docs" }),
  ];
  useBrowserPanelStore.getState().open("c1");
  render(<BrowserPanel browses={tabs} />);
  await userEvent.click(screen.getByRole("tab", { name: "Docs" }));
  expect(useBrowserPanelStore.getState().openCallId).toBe("c2");
  expect(screen.getByRole("tab", { name: "Docs" })).toHaveAttribute("aria-selected", "true");
});

it("resumes a saved page from its panel and closes from the tab strip", async () => {
  const resume = vi.fn();
  useBrowserPanelStore.getState().open("c1");
  render(
    <BrowserPanel
      browses={[browse({ navigable: true, resumable: true, outcome: "done" })]}
      onResume={resume}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Resume session" }));
  expect(resume).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "Close the browser panel" }));
  expect(useBrowserPanelStore.getState().openCallId).toBeNull();
});

it("leaves Escape to dialogs and handlers that already consumed it", () => {
  useBrowserPanelStore.getState().open("c1");
  render(<BrowserPanel browses={[browse()]} />);
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  document.body.append(dialog);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
  dialog.remove();
  const consumed = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
  consumed.preventDefault();
  window.dispatchEvent(consumed);
  expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
});

it("follows the selected tab into its resumed run without selecting a different tab", () => {
  const old = browse({ tabId: "one", navigable: true, outcome: "done" });
  useBrowserPanelStore.getState().open("c1");
  render(
    <BrowserPanel
      browses={[
        old,
        browse({
          callId: "resumed",
          tabId: "one",
          navigable: true,
          runId: "new-run",
          title: "Resumed page",
        }),
        browse({ callId: "other", tabId: "two", navigable: true, title: "Other page" }),
      ]}
    />,
  );
  expect(screen.getByRole("heading", { name: "Resumed page" })).toBeInTheDocument();
  expect(live.calls.at(-1)).toEqual(["new-run", "resumed", true]);
});
