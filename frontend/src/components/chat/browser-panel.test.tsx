import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { BrowserPanel } from "./browser-panel";
import type { Browse } from "@/lib/browse";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";

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
  useBrowserPanelStore.setState({ isOpen: true, dismissed: [] });
});

describe("BrowserPanel - what the browser is doing, while it is doing it", () => {
  it("draws nothing when nothing has browsed", () => {
    const { container } = render(<BrowserPanel browses={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing while closed, however many browses there are", () => {
    useBrowserPanelStore.setState({ isOpen: false });
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

  it("shows the running browse when a turn has browsed twice", () => {
    render(
      <BrowserPanel
        browses={[
          browse({ callId: "c1", title: "First", outcome: "done" }),
          browse({ callId: "c2", title: "Second" }),
        ]}
      />,
    );

    expect(screen.getByText("Second")).toBeInTheDocument();
    expect(screen.queryByText("First")).not.toBeInTheDocument();
  });

  it("stays closed for the browse the person closed it on", async () => {
    // Closing is about this browse, not this frame. Re-opening on the next step
    // would make the control useless exactly when it is being used.
    const user = userEvent.setup();
    render(<BrowserPanel browses={[browse()]} />);

    await user.click(screen.getByLabelText("Close the browser panel"));

    expect(useBrowserPanelStore.getState().isOpen).toBe(false);
    useBrowserPanelStore.getState().openFor("c1");
    expect(useBrowserPanelStore.getState().isOpen).toBe(false);
  });

  it("opens again for the next browse", () => {
    useBrowserPanelStore.setState({ isOpen: false, dismissed: ["c1"] });

    useBrowserPanelStore.getState().openFor("c2");

    expect(useBrowserPanelStore.getState().isOpen).toBe(true);
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<BrowserPanel browses={[browse()]} />);

    await user.keyboard("{Escape}");

    expect(useBrowserPanelStore.getState().isOpen).toBe(false);
  });
});
