import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useFillChatBands } from "./use-fill-chat-bands";

afterEach(() => vi.unstubAllGlobals());

it("opens groups in order only while there is unused height, and reacts to resize", async () => {
  const element = document.createElement("div");
  const content = document.createElement("div");
  element.append(content);
  const ref = { current: element };
  let height = 600;
  let opened: readonly string[] = [];
  Object.defineProperty(element, "clientHeight", { get: () => height });
  Object.defineProperty(element, "scrollHeight", {
    get: () => Math.max(height, 200 + opened.length * 450),
  });
  vi.spyOn(content, "getBoundingClientRect").mockImplementation(
    () => new DOMRect(0, 0, 200, 200 + opened.length * 450),
  );
  const observers: (() => void)[] = [];
  const disconnected = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        observers.push(callback);
      }
      observe() {}
      disconnect = disconnected;
    },
  );
  const candidates = ["week", "month", "older"];
  const result = renderHook(() => {
    opened = useFillChatBands(ref, candidates);
    return opened;
  });
  await waitFor(() => expect(result.result.current).toEqual(["week"]));
  height = 1200;
  act(() => observers.at(-1)?.());
  await waitFor(() => expect(result.result.current).toEqual(["week", "month", "older"]));
  // No candidates are written to the persistent user-choice store.
  result.unmount();
  expect(disconnected).toHaveBeenCalled();
});

it("does not expand groups while their list is hidden", () => {
  const element = document.createElement("div");
  const ref = { current: element };
  Object.defineProperty(element, "clientHeight", { value: 0, configurable: true });
  const candidates = ["month"];
  const { result, rerender } = renderHook(() => useFillChatBands(ref, candidates));
  expect(result.current).toEqual([]);
  Object.defineProperty(element, "clientHeight", { value: 900 });
  rerender();
  // The resize observer, rather than a render unrelated to geometry, drives filling.
  expect(result.current).toEqual([]);
});

it("does not attach an observer before the list is mounted", () => {
  const { result } = renderHook(() => useFillChatBands({ current: null }, ["week"]));
  expect(result.current).toEqual([]);
});

it("counts content and padding before opening another group", () => {
  const element = document.createElement("div");
  const content = document.createElement("div");
  element.append(content);
  element.style.padding = "20px 0";
  Object.defineProperty(element, "clientHeight", { value: 300 });
  Object.defineProperty(element, "scrollHeight", { value: 300 });
  vi.spyOn(content, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 200, 270));
  const { result } = renderHook(() => useFillChatBands({ current: element }, ["week"]));
  expect(result.current).toEqual([]);
});
