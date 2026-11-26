import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOrgStore } from "@/stores/org-store";
import type { Organization } from "@/types";

import { useChatPrompt } from "./use-chat-prompt";

const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
const organizations = vi.hoisted(() => ({
  isSuccess: true,
  isError: false,
  data: [] as Organization[] | undefined,
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => params.value }));
vi.mock("./use-organizations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./use-organizations")>()),
  useOrganizationList: () => organizations,
}));

const defaultOrg = {
  id: "org-1",
  name: "Default",
  is_default: true,
  is_personal: false,
} as Organization;

beforeEach(() => {
  params.value = new URLSearchParams();
  window.history.replaceState({}, "", "/chat");
  organizations.isSuccess = true;
  organizations.isError = false;
  organizations.data = [];
  useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: [] });
});

describe("useChatPrompt", () => {
  it("keeps a cold-load prompt until the initial organization selection settles", () => {
    useOrgStore.setState({ activeOrgId: null });
    organizations.isSuccess = false;
    organizations.data = undefined;
    window.history.replaceState({}, "", "/chat?prompt=Draft");
    params.value = new URLSearchParams("prompt=Draft");

    const { result, rerender } = renderHook(() => useChatPrompt());
    expect(result.current).toBeUndefined();
    expect(window.location.search).toBe("?prompt=Draft");

    organizations.isSuccess = true;
    organizations.data = [defaultOrg];
    rerender();
    expect(result.current).toBeUndefined();
    expect(window.location.search).toBe("?prompt=Draft");

    act(() => useOrgStore.getState().setActiveOrgId(defaultOrg.id));
    expect(result.current?.text).toBe("Draft");
    result.current?.consume();
    expect(window.location.search).toBe("");

    params.value = new URLSearchParams(window.location.search);
    rerender();
    act(() => useOrgStore.getState().setActiveOrgId("org-2"));
    expect(result.current).toBeUndefined();
  });

  it("offers the draft when a successful lookup has no organizations", () => {
    useOrgStore.setState({ activeOrgId: null });
    params.value = new URLSearchParams("prompt=Draft");

    expect(renderHook(() => useChatPrompt()).result.current?.text).toBe("Draft");
  });

  it("offers the draft when every organization has been refused", () => {
    useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [defaultOrg.id] });
    organizations.data = [defaultOrg];
    params.value = new URLSearchParams("prompt=Draft");

    expect(renderHook(() => useChatPrompt()).result.current?.text).toBe("Draft");
  });

  it("preserves the prompt through a failed organization lookup and retry", () => {
    useOrgStore.setState({ activeOrgId: null });
    organizations.isSuccess = false;
    organizations.isError = true;
    organizations.data = undefined;
    window.history.replaceState({}, "", "/chat?prompt=Draft");
    params.value = new URLSearchParams("prompt=Draft");

    const { result, rerender } = renderHook(() => useChatPrompt());
    expect(result.current).toBeUndefined();
    expect(window.location.search).toBe("?prompt=Draft");

    organizations.isSuccess = true;
    organizations.isError = false;
    organizations.data = [];
    rerender();
    expect(result.current?.text).toBe("Draft");
    expect(window.location.search).toBe("?prompt=Draft");
  });

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
