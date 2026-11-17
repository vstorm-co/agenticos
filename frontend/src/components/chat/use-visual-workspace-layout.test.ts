import { act, fireEvent, renderHook } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useVisualWorkspaceLayout } from "./use-visual-workspace-layout";

const show = vi.fn();
const hide = vi.fn();
let layer: HTMLDivElement;
let slot: HTMLDivElement;
let opener: HTMLButtonElement;

beforeEach(() => {
  vi.clearAllMocks();
  layer = document.createElement("div");
  slot = document.createElement("div");
  opener = document.createElement("button");
  layer.tabIndex = -1;
  layer.showPopover = show;
  layer.hidePopover = hide;
  document.body.append(opener, slot, layer);
  opener.focus();
});
afterEach(() => {
  layer.remove();
  slot.remove();
  opener.remove();
  vi.restoreAllMocks();
});

it("does nothing before its layer is attached, including an early dismissal", () => {
  const close = vi.fn();
  const ref = createRef<HTMLDivElement>();
  const view = renderHook(() => useVisualWorkspaceLayout(ref, null, true, false, close));
  act(() => view.result.current.dismiss());
  expect(close).toHaveBeenCalledTimes(1);
  expect(show).not.toHaveBeenCalled();
});

it("ignores repeated geometry and follows actual pane moves, sizes and collapse", () => {
  const ref = { current: layer };
  const close = vi.fn();
  const rect = vi
    .spyOn(slot, "getBoundingClientRect")
    .mockReturnValue(new DOMRect(600, 40, 660, 700));
  const view = renderHook(() => useVisualWorkspaceLayout(ref, slot, true, false, close));
  const original = view.result.current.bounds;
  fireEvent.scroll(window);
  expect(view.result.current.bounds).toBe(original);
  for (const bounds of [
    new DOMRect(610, 40, 660, 700),
    new DOMRect(610, 50, 660, 700),
    new DOMRect(610, 50, 650, 700),
    new DOMRect(610, 50, 650, 690),
  ]) {
    rect.mockReturnValue(bounds);
    fireEvent.resize(window);
    expect(view.result.current.bounds).toBe(bounds);
  }
  rect.mockReturnValue(new DOMRect(600, 40, 660, 0));
  fireEvent.resize(window);
  expect(view.result.current.bounds).toBeNull();
});

it("leaves Escape to nested menus and dialogs and ignores prevented events", () => {
  const close = vi.fn();
  const ref = { current: layer };
  renderHook(() => useVisualWorkspaceLayout(ref, slot, true, false, close));
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  layer.append(dialog);
  fireEvent.keyDown(dialog, { key: "Escape" });
  const prevented = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
  prevented.preventDefault();
  fireEvent(window, prevented);
  expect(close).not.toHaveBeenCalled();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(1);
  expect(opener).toHaveFocus();
});

it("does not refocus or hide a layer removed by navigation", () => {
  const close = vi.fn();
  const view = renderHook(() =>
    useVisualWorkspaceLayout({ current: layer }, slot, true, false, close),
  );
  opener.remove();
  act(() => view.result.current.dismiss());
  expect(close).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(layer);
  layer.remove();
  view.unmount();
  expect(hide).not.toHaveBeenCalled();
});
