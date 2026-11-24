import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useChatPrompt } from "./use-chat-prompt";

const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => params.value }));

describe("useChatPrompt", () => {
  it("offers the prompt as a draft and takes it off the address when consumed", () => {
    window.history.replaceState({}, "", "/chat?prompt=Draft%20a%20workflow");
    params.value = new URLSearchParams("prompt=Draft a workflow");

    const { result } = renderHook(() => useChatPrompt());

    expect(result.current?.text).toBe("Draft a workflow");
    expect(window.location.search).toBe("?prompt=Draft%20a%20workflow");
    result.current?.consume();
    expect(window.location.search).toBe("");
  });

  it("waits while the address still asks for a new chat", () => {
    // Starting that chat remounts the composer; text written first is lost.
    window.history.replaceState({}, "", "/chat?new=1&prompt=Draft");
    params.value = new URLSearchParams("new=1&prompt=Draft");
    const { result, rerender } = renderHook(() => useChatPrompt());
    expect(result.current).toBeUndefined();

    params.value = new URLSearchParams("prompt=Draft");
    rerender();
    expect(result.current?.text).toBe("Draft");
  });

  it("waits while an agent chat is still starting", () => {
    params.value = new URLSearchParams("with=agent-1&prompt=Draft");
    const { result } = renderHook(() => useChatPrompt());
    expect(result.current).toBeUndefined();
  });

  it("offers nothing without a prompt, or with an empty one", () => {
    params.value = new URLSearchParams("new=1");
    expect(renderHook(() => useChatPrompt()).result.current).toBeUndefined();
    params.value = new URLSearchParams("prompt=");
    expect(renderHook(() => useChatPrompt()).result.current).toBeUndefined();
  });

  it("forgets the prompt once the address no longer carries it", () => {
    params.value = new URLSearchParams("prompt=Draft a workflow");
    const { result, rerender } = renderHook(() => useChatPrompt());
    expect(result.current?.text).toBe("Draft a workflow");

    params.value = new URLSearchParams();
    rerender();
    expect(result.current).toBeUndefined();
  });
});
