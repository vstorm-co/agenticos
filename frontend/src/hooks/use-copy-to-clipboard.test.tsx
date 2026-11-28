import { act, renderHook, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useCopyToClipboard } from "./use-copy-to-clipboard";

const originalExecCommand = Object.getOwnPropertyDescriptor(document, "execCommand");

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  if (originalExecCommand) {
    Object.defineProperty(document, "execCommand", originalExecCommand);
  } else {
    Reflect.deleteProperty(document, "execCommand");
  }
});

it("copies selected text inside a dialog without the Clipboard API and restores focus", async () => {
  vi.stubGlobal("navigator", {});
  const value = "https://example.test/webhook";
  const execCommand = vi.fn(() => {
    const field = screen.getByRole("dialog").querySelector("textarea");
    expect(field).not.toBeNull();
    expect(document.activeElement).toBe(field);
    expect(field?.value).toBe(value);
    expect(field?.selectionStart).toBe(0);
    expect(field?.selectionEnd).toBe(value.length);
    return true;
  });
  Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });
  const { result } = renderHook(() => useCopyToClipboard(), {
    wrapper: ({ children }) => (
      <div role="dialog">
        <button type="button">Copy</button>
        {children}
      </div>
    ),
  });
  const button = screen.getByRole("button", { name: "Copy" });
  button.focus();

  await act(async () => {
    expect(await result.current.copy(value)).toBe(true);
  });

  expect(execCommand).toHaveBeenCalledExactlyOnceWith("copy");
  expect(result.current.copied).toBe(true);
  expect(document.querySelector("textarea")).toBeNull();
  expect(button).toHaveFocus();
});

it("does not try the legacy API when the modern API denies copying", async () => {
  const writeText = vi.fn().mockRejectedValue(new DOMException("Denied", "NotAllowedError"));
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const execCommand = vi.fn().mockReturnValue(true);
  Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });
  const { result } = renderHook(() => useCopyToClipboard());

  await act(async () => {
    expect(await result.current.copy("Draft")).toBe(false);
  });

  expect(writeText).toHaveBeenCalledExactlyOnceWith("Draft");
  expect(execCommand).not.toHaveBeenCalled();
  expect(result.current.copied).toBe(false);
  expect(document.querySelector("textarea")).toBeNull();
});

it("cancels feedback when the copied card unmounts", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  const { result, unmount } = renderHook(() => useCopyToClipboard());
  await act(async () => {
    expect(await result.current.copy("Draft")).toBe(true);
  });
  expect(result.current.copied).toBe(true);
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("does not schedule feedback when an asynchronous copy finishes after unmount", async () => {
  vi.useFakeTimers();
  const { promise: written, resolve: finish } = Promise.withResolvers<void>();
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn(() => written) } });
  const { result, unmount } = renderHook(() => useCopyToClipboard());
  const copied = result.current.copy("Draft");
  unmount();
  finish();
  expect(await copied).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("restarts feedback for a new copy and clears it once", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  const { result } = renderHook(() => useCopyToClipboard(100));
  await act(async () => {
    await result.current.copy("One");
  });
  act(() => vi.advanceTimersByTime(50));
  await act(async () => {
    await result.current.copy("Two");
  });
  act(() => vi.advanceTimersByTime(50));
  expect(result.current.copied).toBe(true);
  act(() => vi.advanceTimersByTime(50));
  expect(result.current.copied).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});
