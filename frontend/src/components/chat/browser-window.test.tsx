import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserWindow, hostOf, type BrowseControl } from "./browser-window";
import type { BrowserCommand } from "@/hooks/use-live-browse";
import type { Browse } from "@/lib/browse";
import { useAuthStore } from "@/stores";

function browse(overrides: Partial<Browse> = {}): Browse {
  return {
    callId: "c1",
    runId: "run-1",
    goal: "find the monthly price of the Pro plan",
    maxSteps: 25,
    url: "https://example.test/pricing",
    title: "Pricing",
    steps: [],
    image: "data:image/jpeg;base64,AAA",
    imageStep: 1,
    outcome: null,
    detail: null,
    ...overrides,
  };
}

function control(canControl = true) {
  const send = vi.fn<(command: BrowserCommand) => void>();
  return { canControl, send } satisfies BrowseControl;
}

beforeEach(() => {
  useAuthStore.setState({ user: { id: "u1", full_name: "Ada", email: "ada@acme.test" } as never });
});

describe("hostOf", () => {
  it("reads the host, keeps an address it cannot parse whole, and is null without one", () => {
    expect(hostOf("https://example.test/a?b=1")).toBe("example.test");
    expect(hostOf("not a url")).toBe("not a url");
    expect(hostOf(null)).toBeNull();
  });
});

describe("BrowserWindow - the agent's browser, drawn as a browser", () => {
  it("names the tab after the page, with a padlock on https and the host in the address bar", () => {
    render(<BrowserWindow browse={browse()} control={null} />);

    expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
    expect(screen.getByTitle("https://example.test/pricing")).toHaveTextContent("example.test");
    expect(screen.getByLabelText("Live")).toBeInTheDocument();
  });

  it("falls back to the host, then to a plain name, before the page has a title", () => {
    const { rerender } = render(
      <BrowserWindow browse={browse({ title: null, url: "http://plain.test/" })} control={null} />,
    );
    expect(screen.getByRole("heading", { name: "plain.test" })).toBeInTheDocument();

    rerender(<BrowserWindow browse={browse({ title: null, url: null })} control={null} />);
    expect(screen.getByRole("heading", { name: "Browser" })).toBeInTheDocument();
    expect(screen.getAllByText("Opening the page…").length).toBeGreaterThan(0);
  });

  it("says it is waiting for a picture while running, and that there is none once over", () => {
    const { rerender } = render(<BrowserWindow browse={browse({ image: null })} control={null} />);
    expect(screen.getByText(/Waiting for the first view/)).toBeInTheDocument();

    rerender(<BrowserWindow browse={browse({ image: null, outcome: "done" })} control={null} />);
    expect(screen.getByText(/without a live preview/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Live")).toBeNull();
  });

  it("puts what the browser is doing now under the page, and how it ended once it has", () => {
    const step = {
      step: 2,
      operation: "CLICK",
      target: "Pro plan",
      reason: "to see it",
      url: null,
    };
    const { rerender } = render(
      <BrowserWindow browse={browse({ steps: [step] })} control={null} />,
    );
    expect(screen.getByText("Clicked")).toBeInTheDocument();
    expect(screen.getByText("Pro plan")).toBeInTheDocument();

    rerender(
      <BrowserWindow browse={browse({ steps: [{ ...step, target: null }] })} control={null} />,
    );
    expect(screen.queryByText("Pro plan")).toBeNull();

    rerender(<BrowserWindow browse={browse({ outcome: "blocked" })} control={null} />);
    expect(screen.getByTestId("browse-outcome")).toHaveTextContent("Blocked by the page");
  });

  it("keeps the steps behind a button, with the goal and what the page said", async () => {
    const step = { step: 1, operation: "NAVIGATE", target: null, reason: "start", url: null };
    render(
      <BrowserWindow
        browse={browse({ steps: [step], detail: "The price is $20", outcome: "done" })}
        control={null}
      />,
    );
    expect(screen.queryByText(/monthly price of the Pro plan/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "1 step" }));

    expect(screen.getByRole("button", { name: "1 step" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/monthly price of the Pro plan/)).toBeInTheDocument();
    expect(screen.getByText("The price is $20")).toBeInTheDocument();
    expect(screen.getByText("start")).toBeInTheDocument();
  });

  it("says there are no steps yet when the list is opened early", async () => {
    render(<BrowserWindow browse={browse({ goal: "" })} control={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Steps" }));
    expect(screen.getByText("No steps yet.")).toBeInTheDocument();
  });

  it("shows what the browse needs from a person while it waits for one", () => {
    const { rerender } = render(
      <BrowserWindow browse={browse({ needs: "Sign in to the portal" })} control={null} />,
    );
    expect(screen.getByText("The agent needs you")).toBeInTheDocument();
    expect(screen.getByText("Sign in to the portal")).toBeInTheDocument();

    rerender(
      <BrowserWindow
        browse={browse({ needs: "Sign in to the portal", outcome: "done" })}
        control={null}
      />,
    );
    expect(screen.queryByText("The agent needs you")).toBeNull();
  });

  it("offers no take-over to somebody who may only watch, or once the browse is over", () => {
    const { rerender } = render(<BrowserWindow browse={browse()} control={control(false)} />);
    expect(screen.queryByRole("button", { name: /Take over/ })).toBeNull();

    rerender(<BrowserWindow browse={browse({ outcome: "done" })} control={control()} />);
    expect(screen.queryByRole("button", { name: /Take over/ })).toBeNull();
  });

  it("takes the browser over, then waits for the step in flight", async () => {
    const live = control();
    render(<BrowserWindow browse={browse()} control={live} />);

    await userEvent.click(screen.getByRole("button", { name: /Take over/ }));

    expect(live.send).toHaveBeenCalledWith({ type: "take_over" });
    expect(screen.getByRole("button", { name: /Taking over/ })).toBeDisabled();
  });

  it("hands the page to its holder - clicks reach it - and hands it back", async () => {
    const live = control();
    render(<BrowserWindow browse={browse({ heldBy: "Ada" })} control={live} />);
    expect(screen.getByText(/You're driving/)).toBeInTheDocument();

    const img = screen.getByRole("img");
    Object.defineProperty(img, "naturalWidth", { value: 100 });
    img.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100 }) as DOMRect;
    fireEvent.click(img, { clientX: 10, clientY: 20 });
    expect(live.send).toHaveBeenCalledWith({ type: "click", x: 10, y: 20 });

    await userEvent.click(screen.getByRole("button", { name: /Hand it back/ }));
    expect(live.send).toHaveBeenCalledWith({ type: "give_back" });
  });

  it("names someone else holding the browser, and offers nothing to take", () => {
    render(<BrowserWindow browse={browse({ heldBy: "Bob" })} control={control()} />);

    expect(screen.getByText("Bob has the browser.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Take over|Hand it back/ })).toBeNull();
  });

  it("stops naming the holder once the browse is over", () => {
    render(
      <BrowserWindow browse={browse({ heldBy: "Bob", outcome: "done" })} control={control()} />,
    );
    expect(screen.queryByText("Bob has the browser.")).toBeNull();
  });

  it("knows a person by their address when they have no name", () => {
    useAuthStore.setState({ user: { id: "u1", full_name: null, email: "ada@acme.test" } as never });
    render(<BrowserWindow browse={browse({ heldBy: "ada@acme.test" })} control={control()} />);
    expect(screen.getByRole("button", { name: /Hand it back/ })).toBeInTheDocument();
  });

  it("is nobody without a signed-in user", () => {
    useAuthStore.setState({ user: null });
    render(<BrowserWindow browse={browse({ heldBy: "Ada" })} control={control()} />);
    expect(screen.getByText("Ada has the browser.")).toBeInTheDocument();
  });

  it("ignores the page without a live view to send to", () => {
    render(<BrowserWindow browse={browse({ heldBy: "Ada" })} control={null} />);
    // No control: holding is drawn, but there is no socket for the click to go to.
    fireEvent.click(screen.getByRole("img"));
    expect(screen.queryByRole("button", { name: /Hand it back/ })).toBeNull();
  });

  it("closes, maximises and restores, and opens on its own page", async () => {
    const onClose = vi.fn();
    const onMaximize = vi.fn();
    const { rerender } = render(
      <BrowserWindow
        browse={browse()}
        control={null}
        onClose={onClose}
        onMaximize={onMaximize}
        newTabHref="/browse/run-1/c1"
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Maximize" }));
    await userEvent.click(screen.getByRole("button", { name: "Close the browser panel" }));
    expect(onMaximize).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.getByRole("link", { name: "Open in a new tab" })).toHaveAttribute(
      "href",
      "/browse/run-1/c1",
    );

    rerender(<BrowserWindow browse={browse()} control={null} onMaximize={onMaximize} maximized />);
    expect(screen.getByRole("button", { name: "Back to the side panel" })).toBeInTheDocument();
  });
});
