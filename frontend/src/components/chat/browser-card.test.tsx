import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { LiveBrowsesProvider, TurnBrowses } from "./browser-card";
import type { ToolCall } from "@/types";
import type { Browse } from "@/lib/browse";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";

function browse(overrides: Partial<Browse> = {}): Browse {
  return {
    callId: "c1",
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
    <LiveBrowsesProvider value={browses}>
      <TurnBrowses calls={calls ?? browses.map((entry) => call(entry.callId))} />
    </LiveBrowsesProvider>
  );
}

const line = () => screen.getByRole("button", { name: "Open in the side panel" });

beforeEach(() => {
  useBrowserPanelStore.setState({ openCallId: null, mode: "full" });
});

describe("TurnBrowses - a browse as one line in its turn", () => {
  it("draws nothing for a turn that did not browse", () => {
    const { container } = render(<BrowserCards browses={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says where the agent is browsing and what it just did", () => {
    render(
      <BrowserCards
        browses={[
          browse({
            image: "data:image/jpeg;base64,AAA",
            steps: [{ step: 1, operation: "CLICK", target: "Pro plan", reason: null, url: null }],
          }),
        ]}
      />,
    );

    expect(line()).toHaveTextContent("Browsing example.test");
    expect(line()).toHaveTextContent("Clicked Pro plan");
    expect(line()).toHaveTextContent("Open");
  });

  it("names the action alone when it has no target, and is opening before its first step", () => {
    const { rerender } = render(
      <BrowserCards
        browses={[
          browse({
            steps: [{ step: 1, operation: "WAIT", target: null, reason: null, url: null }],
          }),
        ]}
      />,
    );
    expect(line()).not.toHaveTextContent("null");

    rerender(<BrowserCards browses={[browse({ url: null })]} />);
    expect(line()).toHaveTextContent("Opening the page…");
  });

  it("says how a finished browse ended", () => {
    render(<BrowserCards browses={[browse({ outcome: "done" })]} />);
    expect(line()).toHaveTextContent("Browsed example.test");
    expect(line()).toHaveTextContent("Finished");
  });

  it("puts what the browse needs from a person first, with the way to take over", () => {
    render(<BrowserCards browses={[browse({ needs: "Sign in to the portal" })]} />);
    expect(line()).toHaveTextContent("Needs you: Sign in to the portal");
    expect(line()).toHaveTextContent("Take over");
  });

  it("opens its browse in the side panel, and says so while it is showing", async () => {
    render(<BrowserCards browses={[browse(), browse({ callId: "c2" })]} />);

    await userEvent.click(screen.getAllByRole("button", { name: "Open in the side panel" })[1]!);

    expect(useBrowserPanelStore.getState()).toMatchObject({ openCallId: "c2", mode: "panel" });
    expect(screen.getAllByRole("button", { name: "Open in the side panel" })[1]).toHaveTextContent(
      "Showing",
    );
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

  it("says the agent browsed the web when the call named no page", () => {
    render(<BrowserCards browses={[]} calls={[call("old")]} />);

    expect(screen.getByText("Browsed the web")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
