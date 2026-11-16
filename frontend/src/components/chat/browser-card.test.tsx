import { act, render, screen } from "@testing-library/react";
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
  useBrowserPanelStore.getState().close();
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
      <BrowserCards
        browses={[browse({ tabId: "one" }), browse({ callId: "c2", tabId: "two", title: "Docs" })]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Docs" })).toBeInTheDocument();
    expect(container.querySelector(".md\\:grid-cols-2")).not.toBeNull();
  });

  it("opens beside the chat, and lets its inline socket go", async () => {
    render(<BrowserCards browses={[browse()]} />);

    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Open beside the chat" }));

    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
    expect(live.calls.at(-1)).toEqual(["run-1", "c1", false]);
    await userEvent.click(
      screen.getByRole("button", { name: /example.test is open in the browser panel/ }),
    );
    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
  });

  it("fetches a finished browse's cached last view", () => {
    render(<BrowserCards browses={[browse({ outcome: "done" })]} />);
    expect(live.calls.at(-1)).toEqual(["run-1", "c1", true]);
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

    expect(screen.getByText("Browsed bing.com")).toBeVisible();
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
  await user.click(screen.getByRole("button", { name: "Pricing" }));
  expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
});

it("leaves panes closed as browser activity arrives and does not steal a computer selection", () => {
  const test = render(<BrowserCards browses={[browse({ navigable: true })]} />);
  expect(useBrowserPanelStore.getState().surface).toBeNull();
  test.rerender(<BrowserCards browses={[browse({ nativeId: "native", runId: "next" })]} />);
  expect(useBrowserPanelStore.getState().surface).toBeNull();
  act(() => useBrowserPanelStore.getState().openSurface("computer"));
  test.rerender(<BrowserCards browses={[browse({ callId: "new", navigable: true })]} />);
  expect(useBrowserPanelStore.getState().surface).toBe("computer");
});

it("opens a computer preview in the Computer pane without stale browser chrome", async () => {
  render(
    <BrowserCards
      browses={[browse({ callId: "desktop", title: "Old browser title" })]}
      calls={[{ id: "desktop", name: "computer_screenshot", args: {}, status: "completed" }]}
    />,
  );
  expect(screen.getByRole("heading", { name: "Computer" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Old browser title" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Computer options" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Open beside the chat" }));
  expect(useBrowserPanelStore.getState()).toMatchObject({
    surface: "computer",
    openCallId: "desktop",
  });
  expect(live.calls.at(-1)).toEqual(["run-1", "desktop", false]);
  await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
  expect(useBrowserPanelStore.getState().surface).toBe("computer");
});

it("keeps legacy previews without a run or host readable in the panel", () => {
  const entry = browse({ runId: null, url: null, title: null });
  const { rerender } = render(<BrowserCards browses={[entry]} />);
  expect(live.calls.at(-1)).toEqual(["", "c1", false]);
  act(() => useBrowserPanelStore.getState().open("c1"));
  rerender(<BrowserCards browses={[entry]} />);
  expect(
    screen.getByRole("button", { name: "Browser is open in the browser panel" }),
  ).toBeInTheDocument();
});

it("labels browser links with their host or the browser name when no title is available", () => {
  render(
    <BrowserCards
      browses={[
        browse({ navigable: true, tabId: "one", title: null }),
        browse({ callId: "c2", tabId: "two", navigable: true, title: null, url: null }),
      ]}
    />,
  );
  expect(screen.getByRole("button", { name: "Browsed example.test" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Browsed the web" })).toBeInTheDocument();
});

it("recovers a visited article's identity from its stored result when its arguments contain no URL", () => {
  render(
    <BrowserCards
      browses={[]}
      calls={[
        {
          ...call("article"),
          name: "browser_click",
          args: { element: 12 },
          result:
            "Done: clicked element 12.\n\nPAGE: Article about Poland - https://www.onet.pl/news/poland\nSCROLL: more below",
        },
      ]}
    />,
  );
  expect(screen.getByText("Article about Poland")).toBeVisible();
  expect(screen.getByText("onet.pl")).toBeVisible();
  expect(screen.getByRole("link", { name: /Visit site/ })).toHaveAttribute(
    "href",
    "https://www.onet.pl/news/poland",
  );
  expect(screen.queryByText("Browsed the web")).toBeNull();
});

it("updates one card as the same tab clicks, reads, scrolls and goes back", () => {
  const page = (id: string, name: string, title: string, url: string): ToolCall => ({
    id,
    name,
    args: {},
    status: "completed",
    result: `PAGE: ${title} - ${url}\nSCROLL: more below`,
  });
  render(
    <BrowserCards
      browses={[]}
      calls={[
        page("open", "browser_open", "Onet", "https://onet.pl/"),
        page("click", "browser_click", "Article", "https://onet.pl/article"),
        page("read", "browser_read", "Article", "https://onet.pl/article"),
        page("scroll", "browser_scroll", "Article", "https://onet.pl/article"),
        page("back", "browser_back", "Onet", "https://onet.pl/"),
      ]}
    />,
  );
  expect(screen.getAllByRole("link", { name: /Visit site/ })).toHaveLength(1);
  expect(screen.getByRole("link", { name: /Visit site/ })).toHaveAttribute(
    "href",
    "https://onet.pl/",
  );
});

it("does not add a historical card beside a live view when the same tab is read again", () => {
  render(
    <BrowserCards
      browses={[browse({ callId: "open", navigable: true, tabId: "main" })]}
      calls={[
        { ...call("open"), name: "browser_open" },
        {
          ...call("read"),
          name: "browser_read",
          result: "PAGE: Pricing - https://example.test/pricing",
        },
      ]}
    />,
  );
  expect(screen.getAllByRole("button", { name: "Pricing" })).toHaveLength(1);
  expect(screen.queryByRole("link", { name: /Visit site/ })).toBeNull();
});
