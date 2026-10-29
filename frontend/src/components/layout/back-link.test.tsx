import { fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BackLink } from "./back-link";

const router = vi.hoisted(() => ({ back: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => router,
}));

const origin = window.location.origin;

/** A Navigation API standing on its last entry, with `previous` before it. */
function cameFrom(previous: string) {
  const list = [
    { url: `${origin}${previous}`, index: 0 },
    { url: `${origin}/agents/a1/evals/r1`, index: 1 },
  ];
  Object.defineProperty(window, "navigation", {
    configurable: true,
    value: Object.assign(new EventTarget(), { currentEntry: list[1], entries: () => list }),
  });
}

function back() {
  render(<BackLink href="/agents/a1?tab=evals" label="Back to the agent's evals" />);
}

afterEach(() => {
  Reflect.deleteProperty(window, "navigation");
  vi.clearAllMocks();
});

describe("BackLink", () => {
  it("takes the browser's step back when the page before is one of this app's", async () => {
    cameFrom("/datasets/d1?tab=evals");
    back();

    const link = screen.getByRole("link", { name: "Back" });
    expect(link).toHaveAttribute("href", "/agents/a1?tab=evals");
    await userEvent.click(link);

    expect(router.back).toHaveBeenCalledTimes(1);
  });

  it("opens the logical parent, named, when nothing of this app is before it", async () => {
    back();

    const link = screen.getByRole("link", { name: "Back to the agent's evals" });
    expect(link).toHaveAttribute("href", "/agents/a1?tab=evals");
    fireEvent.click(link);

    expect(router.back).not.toHaveBeenCalled();
  });

  it("leaves a click meant for a new tab to the browser", () => {
    cameFrom("/dashboard");
    back();

    fireEvent.click(screen.getByRole("link", { name: "Back" }), { metaKey: true });

    expect(router.back).not.toHaveBeenCalled();
  });

  it("names the parent in the server's render, before the page can know what came before", () => {
    cameFrom("/dashboard");
    const html = renderToString(
      <BackLink href="/agents/a1?tab=evals" label="Back to the agent's evals" />,
    );
    expect(html).toContain("Back to the agent&#x27;s evals");
  });
});
