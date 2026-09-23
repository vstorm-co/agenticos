import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserPanel } from "./browser-panel";
import type { Browse } from "@/lib/browse";
import {
  DEFAULT_PANEL_WIDTH,
  MAX_PANEL_WIDTH,
  MIN_PANEL_WIDTH,
  useBrowserPanelStore,
} from "@/stores/browser-panel-store";

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

beforeEach(() => {
  useBrowserPanelStore.setState({
    openCallId: "c1",
    mode: "panel",
    width: DEFAULT_PANEL_WIDTH,
  });
});

describe("BrowserPanel - what the browser is doing, while it is doing it", () => {
  it("draws nothing when nothing has browsed", () => {
    const { container } = render(<BrowserPanel browses={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing while closed, however many browses there are", () => {
    useBrowserPanelStore.setState({ openCallId: null });
    const { container } = render(<BrowserPanel browses={[browse()]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the page it is on and the goal it was given", () => {
    render(<BrowserPanel browses={[browse()]} />);

    expect(screen.getByText("Pricing")).toBeInTheDocument();
    expect(screen.getByText("https://example.test/pricing")).toBeInTheDocument();
    expect(screen.getByText(/monthly price of the Pro plan/)).toBeInTheDocument();
  });

  it("says it is waiting before the first picture arrives", () => {
    render(<BrowserPanel browses={[browse()]} />);
    expect(screen.getByText(/Waiting for the first view/)).toBeInTheDocument();
  });

  it("draws the viewport and says which step it is", () => {
    render(
      <BrowserPanel browses={[browse({ image: "data:image/jpeg;base64,AAA", imageStep: 3 })]} />,
    );

    expect(screen.getByRole("img")).toHaveAttribute("src", "data:image/jpeg;base64,AAA");
    expect(screen.getByText("Step 3 of 25")).toBeInTheDocument();
  });

  it("stops the spinner once the browse has ended", () => {
    render(
      <BrowserPanel
        browses={[browse({ image: "data:image/jpeg;base64,AAA", imageStep: 3, outcome: "done" })]}
      />,
    );

    expect(screen.queryByText("Step 3 of 25")).not.toBeInTheDocument();
  });

  it("lists what was chosen and how sure the engine was", () => {
    // The confidence is why a step is worth listing: a browse that acted on a
    // 0.31 pick is one somebody should look at.
    render(
      <BrowserPanel
        browses={[
          browse({
            steps: [
              { step: 1, operation: "CLICK", target: "Accept all", confidence: 0.31, url: null },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("CLICK")).toBeInTheDocument();
    expect(screen.getByText("Accept all")).toBeInTheDocument();
    expect(screen.getByText("0.31")).toBeInTheDocument();
  });

  it.each([
    ["a confident pick", 0.91],
    ["a middling one", 0.52],
    ["one worth looking at", 0.19],
  ])("shows the number for %s rather than only a colour", (_name, value) => {
    // The confidence is why a step is worth listing. Three bands of colour and
    // no number would throw away the reason it is on screen.
    render(
      <BrowserPanel
        browses={[
          browse({
            steps: [
              { step: 1, operation: "CLICK", target: "Accept", confidence: value, url: null },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText(value.toFixed(2))).toBeInTheDocument();
  });

  it("lists a step from a model that reports no confidence", () => {
    render(
      <BrowserPanel
        browses={[
          browse({
            steps: [{ step: 1, operation: "SCROLL", target: null, confidence: null, url: null }],
          }),
        ]}
      />,
    );

    expect(screen.getByText("SCROLL")).toBeInTheDocument();
  });

  it("draws a browse that has no page to name yet", () => {
    render(<BrowserPanel browses={[browse({ url: null, title: "", goal: "" })]} />);
    expect(screen.getByRole("complementary")).toBeInTheDocument();
  });

  it("says a blocked browse is about the page rather than a crash", () => {
    render(
      <BrowserPanel
        browses={[browse({ outcome: "blocked", detail: "The page asks for a sign-in." })]}
      />,
    );

    expect(screen.getByTestId("browse-outcome")).toHaveTextContent("Blocked by the page");
    expect(screen.getByText("The page asks for a sign-in.")).toBeInTheDocument();
  });

  it("renders the page's own words as text, never as markup", () => {
    render(
      <BrowserPanel
        browses={[browse({ outcome: "blocked", detail: "<img src=x onerror=alert(1)>" })]}
      />,
    );

    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    // The alt text of the viewport is the only image this panel ever draws.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows the browse it was opened on, not whichever is running", () => {
    // A panel that followed the newest browse would swap page under a reader
    // the moment the other one advanced.
    useBrowserPanelStore.setState({ openCallId: "c1" });
    render(
      <BrowserPanel
        browses={[
          browse({ callId: "c1", title: "Poland", outcome: "done" }),
          browse({ callId: "c2", title: "Germany" }),
        ]}
      />,
    );

    expect(screen.getByText("Poland")).toBeInTheDocument();
    expect(screen.queryByText("Germany")).not.toBeInTheDocument();
  });

  it("closes itself when the turn that owned its browse is gone", () => {
    // The browses were dropped and the panel was still open on one of them.
    useBrowserPanelStore.setState({ openCallId: "c9" });
    const { container } = render(<BrowserPanel browses={[browse({ callId: "c1" })]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("takes the whole window in full screen, and carries no resize handle there", () => {
    useBrowserPanelStore.setState({ openCallId: "c1", mode: "full" });
    render(<BrowserPanel browses={[browse()]} />);

    expect(screen.getByRole("complementary")).not.toHaveAttribute("style", /width/);
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("closing returns to the card rather than taking the browse away", async () => {
    const user = userEvent.setup();
    render(<BrowserPanel browses={[browse()]} />);

    await user.click(screen.getByLabelText("Close the browser panel"));

    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
  });

  it("is as wide as somebody dragged it", () => {
    useBrowserPanelStore.setState({ width: 640 });
    render(<BrowserPanel browses={[browse()]} />);

    expect(screen.getByRole("complementary")).toHaveStyle({ width: "640px" });
  });

  it("resizes from the pointer's distance to the right edge", () => {
    render(<BrowserPanel browses={[browse()]} />);
    const handle = screen.getByRole("slider");
    // jsdom reports 1024, so a pointer at 500 leaves 524 to the edge.
    handle.setPointerCapture = vi.fn();

    fireEvent.pointerDown(handle, { pointerId: 1 });
    fireEvent.pointerMove(handle, { pointerId: 1, buttons: 1, clientX: 500 });

    expect(useBrowserPanelStore.getState().width).toBe(window.innerWidth - 500);
  });

  it("ignores a move with no button held, which is a hover", () => {
    useBrowserPanelStore.setState({ width: 500 });
    render(<BrowserPanel browses={[browse()]} />);

    fireEvent.pointerMove(screen.getByRole("slider"), { buttons: 0, clientX: 100 });

    expect(useBrowserPanelStore.getState().width).toBe(500);
  });

  it("resizes with the arrow keys, for anyone not dragging", async () => {
    const user = userEvent.setup();
    useBrowserPanelStore.setState({ width: 500 });
    render(<BrowserPanel browses={[browse()]} />);

    screen.getByRole("slider").focus();
    await user.keyboard("{ArrowLeft}");
    expect(useBrowserPanelStore.getState().width).toBeGreaterThan(500);

    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(useBrowserPanelStore.getState().width).toBeLessThan(500);
  });

  it("clamps the width to what a panel can usefully be", () => {
    const { setWidth } = useBrowserPanelStore.getState();

    setWidth(10);
    expect(useBrowserPanelStore.getState().width).toBe(MIN_PANEL_WIDTH);

    setWidth(99_999);
    expect(useBrowserPanelStore.getState().width).toBe(MAX_PANEL_WIDTH);
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<BrowserPanel browses={[browse()]} />);

    await user.keyboard("{Escape}");

    expect(useBrowserPanelStore.getState().openCallId).toBeNull();
  });
});
