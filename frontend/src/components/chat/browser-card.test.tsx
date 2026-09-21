import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { BrowserCards } from "./browser-card";
import type { Browse } from "@/lib/browse";
import { DEFAULT_PANEL_WIDTH, useBrowserPanelStore } from "@/stores/browser-panel-store";

function browse(overrides: Partial<Browse> = {}): Browse {
  return {
    callId: "c1",
    goal: "find the monthly price of the Pro plan",
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

/** The page's own control, of which there is one per card. */
function pageButton(nth = 0): HTMLElement {
  return screen.getAllByRole("button", { name: "Open in the side panel" })[nth]!;
}

beforeEach(() => {
  useBrowserPanelStore.setState({
    openCallId: null,
    mode: "panel",
    width: DEFAULT_PANEL_WIDTH,
  });
});

describe("BrowserCards - a browse in the transcript, with the page as the card", () => {
  it("draws nothing when nothing has browsed", () => {
    const { container } = render(<BrowserCards browses={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the page it is on and how far along it is", () => {
    render(
      <BrowserCards browses={[browse({ imageStep: 3, image: "data:image/jpeg;base64,A" })]} />,
    );

    expect(screen.getByText("Pricing")).toBeInTheDocument();
    expect(screen.getByText("https://example.test/pricing")).toBeInTheDocument();
    expect(screen.getByText("Step 3 of 25")).toBeInTheDocument();
  });

  it("draws the page itself, not a placeholder for one", () => {
    render(
      <BrowserCards browses={[browse({ image: "data:image/jpeg;base64,AAA", imageStep: 1 })]} />,
    );
    expect(screen.getByRole("img")).toHaveAttribute("src", "data:image/jpeg;base64,AAA");
  });

  it("opens the side panel when the page itself is clicked", async () => {
    // The picture is the primary action: it is what somebody reaching for a
    // small view is reaching for.
    const user = userEvent.setup();
    render(<BrowserCards browses={[browse()]} />);

    await user.click(pageButton());

    expect(useBrowserPanelStore.getState()).toMatchObject({ openCallId: "c1", mode: "panel" });
  });

  it("offers full screen as its own control rather than a guess", async () => {
    const user = userEvent.setup();
    render(<BrowserCards browses={[browse()]} />);

    await user.click(screen.getByRole("button", { name: "Open full screen" }));

    expect(useBrowserPanelStore.getState()).toMatchObject({ openCallId: "c1", mode: "full" });
  });

  it("marks the control whose view is the one on screen", () => {
    useBrowserPanelStore.setState({ openCallId: "c1", mode: "full" });
    render(<BrowserCards browses={[browse()]} />);

    expect(screen.getByRole("button", { name: "Open full screen" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The panel control is the same browse in another view, so not pressed.
    const controls = screen.getAllByRole("button", { name: "Open in the side panel" });
    expect(controls[controls.length - 1]).toHaveAttribute("aria-pressed", "false");
  });

  it("draws one card per browse when a turn browses twice", () => {
    // Two parallel browses are two things happening. A single card would show
    // whichever advanced last and hide half the turn.
    render(
      <BrowserCards
        browses={[
          browse({ callId: "c1", title: "Poland - Wikipedia" }),
          browse({ callId: "c2", title: "Germany - Wikipedia" }),
        ]}
      />,
    );

    expect(screen.getByText("Poland - Wikipedia")).toBeInTheDocument();
    expect(screen.getByText("Germany - Wikipedia")).toBeInTheDocument();
  });

  it("opens the browse whose card was clicked, not the newest one", async () => {
    const user = userEvent.setup();
    render(
      <BrowserCards
        browses={[browse({ callId: "c1" }), browse({ callId: "c2", title: "Second" })]}
      />,
    );

    await user.click(pageButton(0));

    expect(useBrowserPanelStore.getState().openCallId).toBe("c1");
  });

  it("shows the outcome instead of the progress once the browse has ended", () => {
    render(<BrowserCards browses={[browse({ outcome: "blocked", detail: "Sign in first" })]} />);

    expect(screen.getByTestId("card-outcome")).toHaveTextContent("Blocked by the page");
    expect(screen.queryByText(/Step \d/)).not.toBeInTheDocument();
  });

  it("draws a browse whose page has no address yet", () => {
    render(<BrowserCards browses={[browse({ url: null, title: "" })]} />);
    expect(pageButton()).toBeInTheDocument();
  });

  it("counts steps without a ceiling when the agent set none", () => {
    render(<BrowserCards browses={[browse({ maxSteps: null, imageStep: 2 })]} />);
    expect(screen.getByText("Step 2")).toBeInTheDocument();
  });

  it("says it is waiting before the first picture arrives", () => {
    render(<BrowserCards browses={[browse()]} />);
    expect(screen.getByText(/Waiting for the first view/)).toBeInTheDocument();
  });

  it("says nothing about a preview an agent turned off", () => {
    render(<BrowserCards browses={[browse({ outcome: "done" })]} />);
    expect(screen.getByText(/runs without a live preview/)).toBeInTheDocument();
  });

  it("renders a page's own words as text, never as markup", () => {
    render(<BrowserCards browses={[browse({ title: "<img src=x onerror=alert(1)>" })]} />);

    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
