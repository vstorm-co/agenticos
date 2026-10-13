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

/** The page itself, the second "side panel" control of each card after its toolbar's. */
function pageButton(nth = 0): HTMLElement {
  return screen.getAllByRole("button", { name: "Open in the side panel" })[nth * 2 + 1]!;
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

  it("shows the site it is on, that it is live, and how far along it is", () => {
    render(
      <BrowserCards browses={[browse({ imageStep: 3, image: "data:image/jpeg;base64,A" })]} />,
    );

    expect(screen.getByText("example.test")).toBeInTheDocument();
    expect(screen.getByTitle("https://example.test/pricing")).toHaveTextContent(
      "example.test/pricing",
    );
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText("Step 3 of 25")).toBeInTheDocument();
  });

  it("says what it is doing now, and why", () => {
    render(
      <BrowserCards
        browses={[
          browse({
            steps: [
              { step: 1, operation: "SCROLL", target: null, reason: "Find the plans", url: null },
              {
                step: 2,
                operation: "CLICK",
                target: "Pricing",
                reason: "Open the pricing page",
                url: null,
              },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("Clicked")).toBeInTheDocument();
    expect(screen.getByText("Pricing")).toBeInTheDocument();
    expect(screen.getByText("Open the pricing page")).toBeInTheDocument();
    expect(screen.queryByText("Find the plans")).not.toBeInTheDocument();
  });

  it("shows a site's root as the host alone, and the last step of a finished browse", () => {
    render(
      <BrowserCards
        browses={[
          browse({
            url: "https://example.test/",
            outcome: "done",
            steps: [{ step: 4, operation: "DONE", target: null, reason: "Report", url: null }],
          }),
        ]}
      />,
    );
    expect(screen.getByTitle("https://example.test/")).toHaveTextContent(/^example\.test$/);
    // The badge, and the last step's own verb.
    expect(screen.getAllByText("Finished")).toHaveLength(2);
    expect(screen.queryByText(/Step \d/)).not.toBeInTheDocument();
  });

  it("says it is opening the page before the first step", () => {
    render(<BrowserCards browses={[browse()]} />);
    expect(screen.getByText("Opening the page…")).toBeInTheDocument();
  });

  it("names a page whose address is not a URL as it was given", () => {
    render(<BrowserCards browses={[browse({ url: "not a url" })]} />);
    expect(screen.getByTitle("not a url")).toHaveTextContent("not a url");
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
    const [toolbar] = screen.getAllByRole("button", { name: "Open in the side panel" });
    expect(toolbar).toHaveAttribute("aria-pressed", "false");
  });

  it("draws one card per browse when a turn browses twice", () => {
    // Two parallel browses are two things happening. A single card would show
    // whichever advanced last and hide half the turn.
    render(
      <BrowserCards
        browses={[
          browse({ callId: "c1", url: "https://pl.wikipedia.org/wiki/Polska" }),
          browse({ callId: "c2", url: "https://de.wikipedia.org/wiki/Deutschland" }),
        ]}
      />,
    );

    expect(screen.getByText("pl.wikipedia.org")).toBeInTheDocument();
    expect(screen.getByText("de.wikipedia.org")).toBeInTheDocument();
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
    render(
      <BrowserCards
        browses={[
          browse({
            steps: [
              {
                step: 1,
                operation: "CLICK",
                target: "<img src=x onerror=alert(1)>",
                reason: null,
                url: null,
              },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("BrowserCards - a way into the live view (#2128)", () => {
  it("links a running browse to its live view, beside the chat", () => {
    render(<BrowserCards browses={[browse({ runId: "run-7" })]} />);

    const link = screen.getByRole("link", { name: "Take over" });
    expect(link).toHaveAttribute("href", "/browse/run-7/c1");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("says when the agent needs a person, and what for", () => {
    render(<BrowserCards browses={[browse({ runId: "run-7", needs: "Sign in to the portal" })]} />);

    expect(screen.getByText("The agent needs you")).toBeInTheDocument();
    expect(screen.getByText("Sign in to the portal")).toBeInTheDocument();
  });

  it("says who has the browser while a person does", () => {
    render(<BrowserCards browses={[browse({ runId: "run-7", heldBy: "Ada" })]} />);
    expect(screen.getByText("Ada has the browser")).toBeInTheDocument();
  });

  it("offers nothing for a browse with no live view, or one that has ended", () => {
    render(
      <BrowserCards
        browses={[
          browse({ callId: "c1" }),
          browse({ callId: "c2", runId: "run-7", outcome: "done" }),
        ]}
      />,
    );
    expect(screen.queryByRole("link", { name: "Take over" })).not.toBeInTheDocument();
  });

  it("names the step where the agent asked for help", () => {
    render(
      <BrowserCards
        browses={[
          browse({
            steps: [
              { step: 1, operation: "ASK_PERSON", target: null, reason: "Sign in", url: null },
            ],
          }),
        ]}
      />,
    );
    expect(screen.getByText("Asked for help")).toBeInTheDocument();
  });
});
