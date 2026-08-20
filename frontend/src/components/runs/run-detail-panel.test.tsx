import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { RunDetailPanel } from "./run-detail-panel";

/**
 * The run detail as a column beside the list, sized by whoever is reading it.
 *
 * It was an overlay drawer, which is the wrong shape for what people do here:
 * reading a run is comparing it with the rows around it, and an overlay hides
 * exactly those. So the two things worth holding shut are that the boundary
 * moves - by drag *and* by keyboard, because a resizer only a mouse can reach
 * is one a keyboard reader cannot use at all - and that moving it does not step
 * to another run, since the arrow keys mean two different things a few pixels
 * apart on this surface.
 */

vi.mock("@/components/runs/focused-run", () => ({
  FocusedRun: ({ runId, onClose }: { runId: string; onClose?: () => void }) => (
    <div data-testid="focused">
      {runId}
      <button type="button" onClick={onClose}>
        close
      </button>
    </div>
  ),
}));

function openPanel(onFocusRun = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunDetailPanel runId="run-1" onFocusRun={onFocusRun} />
    </NextIntlClientProvider>,
  );
  return onFocusRun;
}

function panel() {
  return screen.getByLabelText("Run detail");
}

function handle() {
  return screen.getByLabelText("Resize the run detail");
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("the panel beside the list", () => {
  it("holds the run detail and hands it the way back to the list", async () => {
    // The dismissal lives in the detail's own controls row rather than floated
    // over its header, where it landed on the step arrows at the widths this
    // panel is most often dragged to.
    const onFocusRun = openPanel();

    expect(screen.getByTestId("focused")).toHaveTextContent("run-1");
    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(onFocusRun).toHaveBeenCalledWith(null);
  });

  it("closes on Escape, which a dialog used to do for free", async () => {
    const onFocusRun = openPanel();

    await userEvent.keyboard("{Escape}");

    expect(onFocusRun).toHaveBeenCalledWith(null);
  });

  it("leaves any other key alone", async () => {
    const onFocusRun = openPanel();

    await userEvent.keyboard("a");

    expect(onFocusRun).not.toHaveBeenCalled();
  });

  it("carries its width as a property, so only the two-column layout applies it", () => {
    // `style={{ width }}` would size the panel on a phone too, where it is the
    // whole page rather than a column beside one.
    openPanel();

    expect(panel().style.getPropertyValue("--run-panel-width")).toBe("560px");
  });
});

describe("moving the boundary", () => {
  function drag(toClientX: number) {
    fireEvent.mouseDown(handle());
    fireEvent.mouseMove(window, { clientX: toClientX });
    fireEvent.mouseUp(window);
  }

  it("remembers a dragged width across sessions", () => {
    openPanel();

    drag(window.innerWidth - 700);

    expect(localStorage.getItem("runDetailPanelWidth")).toBe("700");
  });

  it("keeps the width inside bounds the panel is still readable at", () => {
    openPanel();

    drag(window.innerWidth - 10);

    expect(localStorage.getItem("runDetailPanelWidth")).toBe("380");
  });

  it("reads the remembered width as the first paint, not a frame later", () => {
    localStorage.setItem("runDetailPanelWidth", "820");

    openPanel();

    expect(panel().style.getPropertyValue("--run-panel-width")).toBe("820px");
  });

  it("moves on the arrow keys, left widening the panel", async () => {
    // The boundary is the panel's left edge, so left gives it the room the list
    // gives up. A resizer only a mouse can reach is one a keyboard reader cannot
    // move at all.
    openPanel();
    handle().focus();

    await userEvent.keyboard("{ArrowLeft}");
    expect(panel().style.getPropertyValue("--run-panel-width")).toBe("592px");

    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(panel().style.getPropertyValue("--run-panel-width")).toBe("528px");
    expect(localStorage.getItem("runDetailPanelWidth")).toBe("528");
  });

  it("does not step to another run while the boundary has focus", async () => {
    // The same two keys walk the conversation from anywhere else in the panel,
    // so the handle has to stop the event rather than do both at once.
    const stepped = vi.fn();
    window.addEventListener("keydown", stepped);
    openPanel();
    handle().focus();

    await userEvent.keyboard("{ArrowLeft}");

    expect(stepped).not.toHaveBeenCalled();
    window.removeEventListener("keydown", stepped);
  });

  it("ignores a key that is not an arrow", async () => {
    openPanel();
    handle().focus();

    await userEvent.keyboard("{Enter}");

    expect(panel().style.getPropertyValue("--run-panel-width")).toBe("560px");
  });

  it("survives a browser that refuses to store anything", () => {
    // Private mode, or a full quota. Dropping the persistence is the right
    // answer; throwing mid-drag is not.
    openPanel();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });

    expect(() => drag(window.innerWidth - 700)).not.toThrow();
    expect(() => fireEvent.keyDown(handle(), { key: "ArrowLeft" })).not.toThrow();
  });
});
