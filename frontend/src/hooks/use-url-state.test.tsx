import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUrlState } from "./use-url-state";

/**
 * State mirrored into a query parameter, with the parameter winning on a
 * navigation.
 *
 * The two claims that matter: setting writes both the state and the URL, and a
 * navigation that changes the parameter under the state resets the value to it
 * - otherwise the "Show every run" link and a pasted URL would disagree with
 * what the page shows.
 */

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({ useSearchParams: () => params }));

function Probe() {
  const [value, setValue] = useUrlState("agent");
  return (
    <div>
      <output>{value ?? "nothing"}</output>
      <button type="button" onClick={() => setValue("agent-2")}>
        pick
      </button>
      <button type="button" onClick={() => setValue(null)}>
        clear
      </button>
    </div>
  );
}

beforeEach(() => {
  params.delete("agent");
  window.history.replaceState({}, "", "/runs");
});

describe("useUrlState", () => {
  it("opens on what the URL names", () => {
    params.set("agent", "agent-1");
    render(<Probe />);

    expect(screen.getByRole("status")).toHaveTextContent("agent-1");
  });

  it("writes a pick to the state and to the URL", async () => {
    render(<Probe />);

    await userEvent.click(screen.getByRole("button", { name: "pick" }));

    expect(screen.getByRole("status")).toHaveTextContent("agent-2");
    expect(new URL(window.location.href).searchParams.get("agent")).toBe("agent-2");
  });

  it("clears the parameter from the URL when the value is cleared", async () => {
    params.set("agent", "agent-1");
    render(<Probe />);

    await userEvent.click(screen.getByRole("button", { name: "clear" }));

    expect(screen.getByRole("status")).toHaveTextContent("nothing");
    expect(new URL(window.location.href).searchParams.get("agent")).toBeNull();
  });

  it("lets a navigation's parameter win over the state it changes under", async () => {
    const { rerender } = render(<Probe />);
    await userEvent.click(screen.getByRole("button", { name: "pick" }));
    expect(screen.getByRole("status")).toHaveTextContent("agent-2");

    // A navigation rewrites the parameter under the state; the fresh value
    // must win, or the URL and the page would describe two different views.
    params.set("agent", "agent-9");
    rerender(<Probe />);

    expect(screen.getByRole("status")).toHaveTextContent("agent-9");
  });
});
