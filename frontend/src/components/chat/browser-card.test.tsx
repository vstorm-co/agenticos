import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LiveBrowsesProvider, TurnBrowses } from "./browser-card";
import type { ToolCall } from "@/types";
import type { Browse } from "@/lib/browse";
import { useAuthStore } from "@/stores";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";

const live = vi.hoisted(() => ({
  value: {
    browse: null as Browse | null,
    task: "",
    canControl: false,
    canRemember: false,
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

function call(id = "c1", args: Record<string, unknown> = {}): ToolCall {
  return { id, name: "browse_web", args, status: "completed" };
}

/** The turn's `browse_web` calls, drawn against the browses live in the chat. */
function BrowserCards({ browses, calls }: { browses: Browse[]; calls?: ToolCall[] }) {
  return (
    <LiveBrowsesProvider value={{ browses }}>
      <TurnBrowses calls={calls ?? browses.map((entry) => call(entry.callId))} />
    </LiveBrowsesProvider>
  );
}

beforeEach(() => {
  live.value = {
    browse: null,
    task: "",
    canControl: false,
    canRemember: false,
    status: "connecting",
    send: vi.fn(),
  };
  live.calls = [];
  useAuthStore.setState({ user: { id: "u1", full_name: "Ada", email: "ada@acme.test" } as never });
  useBrowserPanelStore.setState({ openCallId: null });
});

describe("TurnBrowses - a browse as a browser under its message", () => {
  it("draws nothing for a turn that did not browse", () => {
    const { container } = render(<BrowserCards browses={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws a running browse as a browser, live, with the way to take over", async () => {
    live.value = {
      ...live.value,
      browse: browse({ title: "Live copy" }),
      canControl: true,
      status: "live",
    };
    render(<BrowserCards browses={[browse()]} />);

    expect(live.calls.at(-1)).toEqual(["run-1", "c1", true]);
    expect(screen.getByRole("heading", { name: "Live copy" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Take over/ }));
    expect(live.value.send).toHaveBeenCalledWith({ type: "take_over" });
  });

  it("sets several side by side, each its own browser", () => {
    const { container } = render(
      <BrowserCards browses={[browse(), browse({ callId: "c2", title: "Docs" })]} />,
    );

    expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
    expect(container.querySelector(".md\\:grid-cols-2")).not.toBeNull();
  });

  it("opens beside the chat, and lets its inline socket go", async () => {
    render(<BrowserCards browses={[browse()]} />);

    await userEvent.click(screen.getByRole("button", { name: "Open beside the chat" }));

    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
    expect(live.calls.at(-1)).toEqual(["run-1", "c1", false]);
    await userEvent.click(
      screen.getByRole("button", { name: /example.test is open in the browser panel/ }),
    );
    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
  });

  it("keeps a finished browse's last view, without a live socket", () => {
    render(<BrowserCards browses={[browse({ outcome: "done" })]} />);
    expect(live.calls.at(-1)).toEqual(["run-1", "c1", false]);
    expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
  });

  it("keeps a browse from an earlier turn, with the way to the site", () => {
    // Nothing live in this chat for it any more - the line used to vanish with
    // the next message.
    render(
      <BrowserCards
        browses={[]}
        calls={[call("old", { start_url: "https://vstorm.co/pricing" })]}
      />,
    );

    expect(screen.getByText("Browsed vstorm.co")).toBeVisible();
    expect(screen.getByRole("link", { name: /Visit site/ })).toHaveAttribute(
      "href",
      "https://vstorm.co/pricing",
    );
  });

  it("names the site a browser_open went to, from its url", () => {
    const opened: ToolCall = {
      id: "open",
      name: "browser_open",
      args: { url: "https://www.bing.com/news/search?q=Poland" },
      status: "completed",
    };
    render(<BrowserCards browses={[]} calls={[opened]} />);

    expect(screen.getByText("Browsed www.bing.com")).toBeVisible();
  });

  it("says the agent browsed the web when the call named no page", () => {
    render(<BrowserCards browses={[]} calls={[call("old")]} />);

    expect(screen.getByText("Browsed the web")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("says once that the agent used a computer, however many runs did", () => {
    const desktop = (id: string, name: string): ToolCall => ({
      id,
      name,
      args: {},
      status: "completed",
    });
    render(
      <BrowserCards
        browses={[]}
        calls={[desktop("look", "computer_screenshot"), desktop("act", "computer_act")]}
      />,
    );

    expect(screen.getAllByText("Used a computer")).toHaveLength(1);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("draws a desktop's window and no line beside it", () => {
    const calls: ToolCall[] = [
      { id: "look", name: "computer_screenshot", args: {}, status: "completed" },
      { id: "act", name: "computer_act", args: {}, status: "completed" },
    ];
    render(<BrowserCards browses={[browse({ callId: "act", url: null })]} calls={calls} />);

    expect(screen.queryByText("Used a computer")).toBeNull();
  });
});

it("opens the native tab panel rather than presenting an empty screenshot", async () => {
  const user = userEvent.setup();
  render(<BrowserCards browses={[browse({ nativeId: "native-browser-test", outcome: "done" })]} />);
  await user.click(screen.getByRole("button", { name: "Open local browser" }));
  expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
});

it("opens a new native browse automatically in the desktop console", () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "0.2.0",
    window: "main",
    vibrancy: true,
  };
  try {
    render(<BrowserCards browses={[browse({ nativeId: "native-browser-test" })]} />);
    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
  } finally {
    delete window.__AGENTICOS_SHELL__;
  }
});
