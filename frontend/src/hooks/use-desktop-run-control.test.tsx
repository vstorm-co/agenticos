import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useDesktopRunControl } from "./use-desktop-run-control";
const event = vi.hoisted(() => ({ callback: (_value: unknown) => {} }));
vi.mock("./use-desktop", () => ({
  useShellEvent: (_name: string, callback: (value: unknown) => void) => {
    event.callback = callback;
  },
}));
beforeEach(() => vi.clearAllMocks());
it("stops only the active originating conversation", () => {
  const stop = vi.fn();
  const view = renderHook(
    ({ conversation, processing, following }) =>
      useDesktopRunControl(conversation, processing, () => following, stop),
    { initialProps: { conversation: "one", processing: true, following: false } },
  );
  event.callback("other");
  event.callback({ conversation: "one" });
  expect(stop).not.toHaveBeenCalled();
  event.callback("one");
  expect(stop).toHaveBeenCalledOnce();
  view.rerender({ conversation: "one", processing: true, following: true });
  event.callback("one");
  view.rerender({ conversation: "one", processing: false, following: false });
  event.callback("one");
  expect(stop).toHaveBeenCalledOnce();
});
