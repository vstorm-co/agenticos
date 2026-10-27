import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
    expect(screen.getByText("Live")).toBeInTheDocument();
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
    expect(screen.getByText(/No saved preview/)).toBeInTheDocument();
    expect(screen.queryByText("Live")).toBeNull();
  });

  it("keeps activity off the page and shows completion in the toolbar", () => {
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
    expect(screen.queryByText("Clicked")).toBeNull();
    expect(screen.queryByText("Pro plan")).toBeNull();

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

    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "1 step" }));
    expect(screen.getByText(/monthly price of the Pro plan/)).toBeInTheDocument();
    expect(screen.getByText("The price is $20")).toBeInTheDocument();
    expect(screen.getByText("start")).toBeInTheDocument();
  });

  it("says there are no steps yet when the list is opened early", async () => {
    render(<BrowserWindow browse={browse({ goal: "" })} control={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Steps" }));
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
    render(<BrowserWindow browse={browse({ heldBy: "Ada", heldById: "u1" })} control={live} />);
    expect(screen.queryByText(/You're driving/)).toBeNull();

    const img = screen.getByRole("img");
    Object.defineProperty(img, "naturalWidth", { value: 100 });
    img.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100 }) as DOMRect;
    fireEvent.click(img, { clientX: 10, clientY: 20 });
    expect(live.send).toHaveBeenCalledWith({ type: "click", x: 10, y: 20 });

    await userEvent.click(screen.getByRole("button", { name: /Hand it back/ }));
    expect(live.send).toHaveBeenCalledWith({ type: "give_back", remember: false });
  });

  it("offers the person the browse acts for to keep the sign-in they made", async () => {
    const live = { ...control(), canRemember: true };
    render(
      <BrowserWindow
        browse={browse({
          heldBy: "Ada",
          heldById: "u1",
          url: "https://portal.example.test/home",
        })}
        control={live}
      />,
    );

    const keep = screen.getByRole("checkbox", { name: /Keep me signed in to portal.example.test/ });
    await userEvent.click(keep);
    await userEvent.click(screen.getByRole("button", { name: /Hand it back/ }));

    expect(live.send).toHaveBeenCalledWith({ type: "give_back", remember: true });
    // The tick was for that hand-back: the next take-over asks again.
    expect(keep).not.toBeChecked();
  });

  it("does not offer to keep a sign-in to someone the browse does not act for", () => {
    render(
      <BrowserWindow browse={browse({ heldBy: "Ada", heldById: "u1" })} control={control()} />,
    );

    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("says which site's sign-in was kept once the browser is handed back", () => {
    render(<BrowserWindow browse={browse({ kept: "portal.example.test" })} control={control()} />);

    expect(screen.getByText(/Your sign-in to portal.example.test is kept/)).toBeVisible();
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

  it("knows the holder by id, so a namesake holding it is not you", () => {
    render(
      <BrowserWindow browse={browse({ heldBy: "Ada", heldById: "u2" })} control={control()} />,
    );
    expect(screen.getByText("Ada has the browser.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Hand it back/ })).toBeNull();
  });

  it("is nobody without a signed-in user", () => {
    useAuthStore.setState({ user: null });
    render(<BrowserWindow browse={browse({ heldBy: "Ada" })} control={control()} />);
    expect(screen.getByText("Ada has the browser.")).toBeInTheDocument();
  });

  it("ignores the page without a live view to send to", () => {
    render(<BrowserWindow browse={browse({ heldBy: "Ada", heldById: "u1" })} control={null} />);
    // No control: holding is drawn, but there is no socket for the click to go to.
    fireEvent.click(screen.getByRole("img"));
    expect(screen.queryByRole("button", { name: /Hand it back/ })).toBeNull();
  });

  it("draws the agent's cursor where it is about to press, while it runs and nobody holds it", () => {
    const pointer = { x: 0.25, y: 0.5, step: 3 };
    const { rerender } = render(<BrowserWindow browse={browse({ pointer })} control={null} />);
    expect(screen.getByTestId("agent-cursor")).toHaveStyle({ left: "25%", top: "50%" });

    rerender(
      <BrowserWindow browse={browse({ pointer, heldBy: "Ada", heldById: "u1" })} control={null} />,
    );
    expect(screen.queryByTestId("agent-cursor")).toBeNull();

    rerender(<BrowserWindow browse={browse({ pointer, outcome: "done" })} control={null} />);
    expect(screen.queryByTestId("agent-cursor")).toBeNull();
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

    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Maximize" }));
    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Close the browser panel" }));
    expect(onMaximize).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    expect(screen.getByRole("menuitem", { name: "Open in a new tab" })).toHaveAttribute(
      "href",
      "/browse/run-1/c1",
    );

    await userEvent.keyboard("{Escape}");
    rerender(<BrowserWindow browse={browse()} control={null} onMaximize={onMaximize} maximized />);
    await userEvent.click(screen.getByRole("button", { name: "Browser options" }));
    expect(screen.getByRole("menuitem", { name: "Back under the message" })).toBeInTheDocument();
  });
});

describe("BrowserWindow - the page laid out for the window showing it", () => {
  let resized: (() => void) | undefined;
  let disconnected = false;

  beforeEach(() => {
    vi.useFakeTimers();
    resized = undefined;
    disconnected = false;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe() {}
        disconnect() {
          disconnected = true;
        }
      },
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /** The page area's size, as the layout would give it. */
  function sized(width: number, height: number) {
    const page = screen.getByRole("img").closest(".relative.min-h-0") as HTMLElement;
    Object.defineProperty(page, "clientWidth", { value: width, configurable: true });
    Object.defineProperty(page, "clientHeight", { value: height, configurable: true });
  }

  it("asks for the window's size once, and again only after it settles on a new one", () => {
    const live = control();
    const { unmount } = render(<BrowserWindow browse={browse()} control={live} />);
    // jsdom lays nothing out, so the first ask is the smallest window there is.
    expect(live.send).toHaveBeenLastCalledWith({
      type: "resize",
      width: 320,
      height: 320,
      scale: 1,
    });

    sized(640.4, 900);
    act(() => resized?.());
    act(() => resized?.());
    expect(live.send).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(250));
    expect(live.send).toHaveBeenLastCalledWith({
      type: "resize",
      width: 640,
      height: 900,
      scale: 1,
    });

    // The same size again lays nothing out again.
    act(() => resized?.());
    act(() => vi.advanceTimersByTime(250));
    expect(live.send).toHaveBeenCalledTimes(2);

    unmount();
    expect(disconnected).toBe(true);
  });

  it("keeps large-screen resize requests within the server limits", () => {
    vi.stubGlobal("devicePixelRatio", 2);
    const live = control();
    render(<BrowserWindow browse={browse()} control={live} />);
    sized(2560, 2160);
    act(() => resized?.());
    act(() => vi.advanceTimersByTime(250));
    expect(live.send).toHaveBeenLastCalledWith({
      type: "resize",
      width: 1600,
      height: 2000,
      scale: 2,
    });
  });

  it("asks for twice the pixels on a high-density screen", () => {
    vi.stubGlobal("devicePixelRatio", 2);
    const live = control();
    render(<BrowserWindow browse={browse()} control={live} />);
    expect(live.send).toHaveBeenLastCalledWith(expect.objectContaining({ scale: 2 }));
  });

  it("leaves the size alone for somebody who may only watch, or a browse that is over", () => {
    const watching = control(false);
    render(<BrowserWindow browse={browse()} control={watching} />);
    const over = control();
    render(<BrowserWindow browse={browse({ outcome: "done" })} control={over} />);

    expect(watching.send).not.toHaveBeenCalled();
    expect(over.send).not.toHaveBeenCalled();
  });
});

describe("BrowserWindow - the address bar", () => {
  it("shows the host and then the path, and an address it cannot parse whole", () => {
    const { rerender } = render(
      <BrowserWindow
        browse={browse({ url: "https://example.test/pricing?plan=pro" })}
        control={null}
      />,
    );
    expect(screen.getByText("example.test")).toBeVisible();
    expect(screen.getByText("/pricing?plan=pro")).toBeVisible();

    rerender(<BrowserWindow browse={browse({ url: "not a url" })} control={null} />);
    expect(screen.getByText("not a url")).toBeVisible();
  });
});

describe("BrowserWindow - the first picture, at the window's own size", () => {
  /** An image whose decoded width the test chooses, since jsdom decodes nothing. */
  function decodesAt(width: number) {
    class Decoded {
      onload: (() => void) | null = null;
      naturalWidth = width;
      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal("Image", Decoded);
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("holds a frame of the default size back, and shows the first of its own", async () => {
    // The window asks for 320 CSS px at density 1 in jsdom, which lays nothing out.
    decodesAt(1280);
    const { rerender } = render(<BrowserWindow browse={browse()} control={control()} waitForFit />);
    await act(async () => {});
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("Waiting for the first view of the page…")).toBeVisible();

    decodesAt(320);
    rerender(
      <BrowserWindow
        browse={browse({ image: "data:image/jpeg;base64,FITTED" })}
        control={control()}
        waitForFit
      />,
    );
    await act(async () => {});
    expect(screen.getByRole("img")).toBeVisible();
  });

  it("shows what it has once waiting for its own size has taken too long", () => {
    vi.useFakeTimers();
    decodesAt(1280);
    render(<BrowserWindow browse={browse()} control={control()} waitForFit />);
    expect(screen.queryByRole("img")).toBeNull();

    act(() => vi.advanceTimersByTime(6000));

    expect(screen.getByRole("img")).toBeVisible();
  });

  it("does not wait where nobody drives the page to its size", () => {
    render(<BrowserWindow browse={browse()} control={null} waitForFit />);

    expect(screen.getByRole("img")).toBeVisible();
  });
});

describe("BrowserWindow - commenting on the page", () => {
  it("offers a comment where there is somewhere to send it, and lays the picker over the page", async () => {
    const onComment = vi.fn();
    const { rerender } = render(<BrowserWindow browse={browse()} control={null} />);
    expect(screen.queryByRole("button", { name: "Comment on the page" })).toBeNull();

    rerender(<BrowserWindow browse={browse()} control={null} onComment={onComment} />);
    const button = screen.getByRole("button", { name: "Comment on the page" });
    await userEvent.click(button);

    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Click the spot you mean")).toBeInTheDocument();
    await userEvent.click(button);
    expect(screen.queryByText("Click the spot you mean")).toBeNull();
  });

  it("puts the picker away once the comment is dropped", async () => {
    render(<BrowserWindow browse={browse()} control={null} onComment={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Comment on the page" }));

    const layer = screen.getByTestId("browser-comment-layer");
    // jsdom lays nothing out; the spot is a fraction of the picture's box.
    vi.spyOn(layer, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 400,
      height: 300,
    } as DOMRect);
    fireEvent.click(layer, { clientX: 5, clientY: 5 });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByTestId("browser-comment-layer")).toBeNull();
  });

  it("offers none without a picture to point at", () => {
    render(<BrowserWindow browse={browse({ image: null })} control={null} onComment={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Comment on the page" })).toBeNull();
  });
});

it("offers address navigation only for browser tabs, with server refusals visible", () => {
  const live = control();
  const { rerender } = render(
    <BrowserWindow
      browse={browse({
        navigable: true,
        heldBy: "Ada",
        heldById: "u1",
        controlError: "Outside allowed domains",
      })}
      control={live}
    />,
  );
  expect(screen.getByRole("textbox", { name: "Website address" })).toHaveValue(
    "https://example.test/pricing",
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Outside allowed domains");
  expect(screen.getByRole("heading", { name: "Pricing" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reload" }));
  expect(live.send).toHaveBeenCalledWith({ type: "reload" });
  rerender(
    <BrowserWindow browse={browse({ navigable: true, url: null, title: null })} control={live} />,
  );
  expect(screen.getByRole("heading", { name: "Browser" })).toBeInTheDocument();
  rerender(<BrowserWindow browse={browse({ navigable: true, title: null })} control={live} />);
  expect(screen.getByRole("heading", { name: "example.test" })).toBeInTheDocument();
  rerender(<BrowserWindow browse={browse({ navigable: false })} control={live} />);
  expect(screen.queryByRole("textbox", { name: "Website address" })).toBeNull();
});
