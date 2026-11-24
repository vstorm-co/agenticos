import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useChatPrompt } from "./use-chat-prompt";

const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => params.value }));

describe("useChatPrompt", () => {
  it("hands the prompt to the composer and takes it off the address", () => {
    window.history.replaceState({}, "", "/chat?new=1&prompt=Draft%20a%20workflow");
    params.value = new URLSearchParams("new=1&prompt=Draft a workflow");

    const { result } = renderHook(() => useChatPrompt());

    expect(result.current?.text).toBe("Draft a workflow");
    expect(result.current?.files).toEqual([]);
    expect(result.current?.id).toEqual(expect.any(Number));
    expect(window.location.search).toBe("?new=1");
  });

  it("hands nothing over without a prompt, and leaves the address alone", () => {
    window.history.replaceState({}, "", "/chat?new=1");
    params.value = new URLSearchParams("new=1");

    const { result } = renderHook(() => useChatPrompt());

    expect(result.current).toBeNull();
    expect(window.location.search).toBe("?new=1");
  });

  it("ignores an empty prompt", () => {
    window.history.replaceState({}, "", "/chat?prompt=");
    params.value = new URLSearchParams("prompt=");

    const { result } = renderHook(() => useChatPrompt());

    expect(result.current).toBeNull();
    expect(window.location.search).toBe("?prompt=");
  });

  it("keeps the same hand-off across re-renders so the composer writes it once", () => {
    params.value = new URLSearchParams("prompt=Draft a workflow");
    const { result, rerender } = renderHook(() => useChatPrompt());
    const first = result.current;
    rerender();
    rerender();
    expect(result.current).toBe(first);
  });

  it("forgets the prompt once the address no longer carries it", () => {
    params.value = new URLSearchParams("prompt=Draft a workflow");
    const { result, rerender } = renderHook(() => useChatPrompt());
    expect(result.current?.text).toBe("Draft a workflow");

    params.value = new URLSearchParams();
    rerender();

    expect(result.current).toBeNull();
  });
});
