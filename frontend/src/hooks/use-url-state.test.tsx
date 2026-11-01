import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { takeOwnTraversal } from "@/lib/history-entries";
import { useUrlList, useUrlOverlay, useUrlState } from "./use-url-state";

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

function Overlay() {
  const [value, view] = useUrlOverlay("case");
  return (
    <div>
      <output>{value ?? "nothing"}</output>
      <button type="button" onClick={() => view.open("c1")}>
        open c1
      </button>
      <button type="button" onClick={() => view.open("c2")}>
        open c2
      </button>
      <button
        type="button"
        onClick={() => {
          // A dialog reports closing twice: once as it discards, once as it goes.
          view.close();
          view.close();
        }}
      >
        close
      </button>
      <button type="button" onClick={() => view.replace(null)}>
        clear
      </button>
    </div>
  );
}

function ListProbe() {
  const [values, setValues] = useUrlList("outcome");
  return (
    <div>
      <output>{values.join("|") || "nothing"}</output>
      <button type="button" onClick={() => setValues(["a", "b"])}>
        pick
      </button>
      <button type="button" onClick={() => setValues([])}>
        clear
      </button>
    </div>
  );
}

describe("useUrlOverlay", () => {
  beforeEach(() => {
    params.delete("case");
    takeOwnTraversal();
    window.history.replaceState({}, "", "/datasets/d1");
  });

  it("opens an object from its page as a step of its own, and the next one in its place", async () => {
    render(<Overlay />);
    const length = window.history.length;

    await userEvent.click(screen.getByRole("button", { name: "open c1" }));
    expect(screen.getByRole("status")).toHaveTextContent("c1");
    expect(window.history.length).toBe(length + 1);
    expect(new URL(window.location.href).searchParams.get("case")).toBe("c1");
    expect((window.history.state as Record<string, unknown>).__urlOverlay).toBe("case");

    await userEvent.click(screen.getByRole("button", { name: "open c2" }));
    expect(screen.getByRole("status")).toHaveTextContent("c2");
    expect(window.history.length).toBe(length + 1);
    expect(new URL(window.location.href).searchParams.get("case")).toBe("c2");
  });

  it("closes by going back over the step it opened, once however often it is asked", async () => {
    const go = vi.spyOn(window.history, "go").mockImplementation(() => {});
    render(<Overlay />);
    await userEvent.click(screen.getByRole("button", { name: "open c1" }));
    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(screen.getByRole("status")).toHaveTextContent("nothing");
    expect(go).toHaveBeenCalledTimes(1);
    expect(go).toHaveBeenCalledWith(-1);
    go.mockRestore();
  });

  it("goes back past the unsaved-changes guard's copy of the step", async () => {
    const go = vi.spyOn(window.history, "go").mockImplementation(() => {});
    render(<Overlay />);
    await userEvent.click(screen.getByRole("button", { name: "open c1" }));
    window.history.pushState(
      { ...window.history.state, __unsavedHeld: true },
      "",
      window.location.href,
    );
    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(go).toHaveBeenCalledWith(-2);
    go.mockRestore();
  });

  it("drops the parameter in place when a link opened the object", async () => {
    const go = vi.spyOn(window.history, "go");
    params.set("case", "c1");
    window.history.replaceState({}, "", "/datasets/d1?case=c1");
    render(<Overlay />);
    const length = window.history.length;

    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(screen.getByRole("status")).toHaveTextContent("nothing");
    expect(go).not.toHaveBeenCalled();
    expect(window.history.length).toBe(length);
    expect(new URL(window.location.href).searchParams.get("case")).toBeNull();
    go.mockRestore();
  });

  it("does nothing to close when nothing is open, and clears in place on request", async () => {
    const go = vi.spyOn(window.history, "go");
    render(<Overlay />);
    await userEvent.click(screen.getByRole("button", { name: "close" }));
    expect(go).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "open c1" }));
    await userEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(screen.getByRole("status")).toHaveTextContent("nothing");
    expect(new URL(window.location.href).searchParams.get("case")).toBeNull();
    go.mockRestore();
  });
});

describe("useUrlList", () => {
  beforeEach(() => {
    params.delete("outcome");
    window.history.replaceState({}, "", "/logs");
  });

  it("opens on every occurrence of the parameter", () => {
    params.append("outcome", "error");
    params.append("outcome", "out");
    render(<ListProbe />);
    expect(screen.getByRole("status")).toHaveTextContent("error|out");
  });

  it("rewrites every occurrence in the URL, and clears them", async () => {
    window.history.replaceState({}, "", "/logs?outcome=old&outcome=older");
    render(<ListProbe />);
    await userEvent.click(screen.getByRole("button", { name: "pick" }));
    expect(screen.getByRole("status")).toHaveTextContent("a|b");
    expect(new URL(window.location.href).searchParams.getAll("outcome")).toEqual(["a", "b"]);

    await userEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(screen.getByRole("status")).toHaveTextContent("nothing");
    expect(new URL(window.location.href).searchParams.getAll("outcome")).toEqual([]);
  });

  it("lets a navigation's values win over the state", async () => {
    const { rerender } = render(<ListProbe />);
    await userEvent.click(screen.getByRole("button", { name: "pick" }));
    params.append("outcome", "x");
    params.append("outcome", "y");
    rerender(<ListProbe />);
    expect(screen.getByRole("status")).toHaveTextContent("x|y");
  });
});
