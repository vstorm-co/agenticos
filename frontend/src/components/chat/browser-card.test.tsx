import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { BrowserCards } from "./browser-card";
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

const line = () => screen.getByRole("button", { name: "Open in the side panel" });

beforeEach(() => {
  useBrowserPanelStore.setState({ openCallId: null, mode: "full" });
});

describe("BrowserCards - a browse as one line in the transcript", () => {
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
});
