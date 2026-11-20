import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantPageDetails } from "@/lib/assistant-page-context";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useAssistantPageContextStore } from "@/stores/assistant-page-context-store";

import {
  useAssistantPageContext,
  useRegisterAssistantPageContext,
} from "./use-assistant-page-context";

const route = vi.hoisted(() => ({ path: "/apps/scheduler" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.path }));

const detail = (): AssistantPageDetails => ({
  title: "Scheduler",
  resource: { kind: "app", id: "scheduler", title: "Scheduler" },
  view: "Week",
  filters: { status: "pending" },
  selected_ids: ["job-1"],
  summary: "One job is selected.",
});

function navigate(path: string) {
  route.path = path;
  window.history.replaceState({}, "", path);
}

beforeEach(() => {
  useAssistantPageContextStore.setState({ registrations: [] });
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
  navigate("/apps/scheduler");
  document.title = "Scheduling page";
});

afterEach(() => {
  useAssistantPageContextStore.setState({ registrations: [] });
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
  document.title = "";
});

describe("the floating assistant's current page", () => {
  it("follows navigation and title changes without reading forms or page text", async () => {
    const input = document.createElement("input");
    input.value = "private-form-value";
    document.body.append(input);
    try {
      const { result, rerender } = renderHook(() => useAssistantPageContext(route.path));
      expect(result.current.getSnapshot()).toMatchObject({
        path: "/apps/scheduler",
        title: "Scheduling page",
      });
      expect(JSON.stringify(result.current.getSnapshot())).not.toContain("private-form-value");
      expect(result.current.getSnapshot()).not.toHaveProperty("selected_text");
      act(() => {
        navigate("/en/runs?token=private-query#secret-fragment");
        document.title = "Runs";
      });
      rerender();
      await waitFor(() => expect(result.current.page.title).toBe("Runs"));
      expect(result.current.getSnapshot()).toMatchObject({ path: "/runs", title: "Runs" });
      expect(JSON.stringify(result.current.getSnapshot())).not.toContain("private-query");
    } finally {
      input.remove();
    }
  });

  it("shares explicit details only while their page registration is mounted", () => {
    const provider = renderHook(() => useRegisterAssistantPageContext(detail()));
    const reader = renderHook(() => useAssistantPageContext(route.path));
    expect(reader.result.current.getSnapshot()).toMatchObject(detail());
    act(() => provider.unmount());
    expect(reader.result.current.getSnapshot()).not.toHaveProperty("resource");
    expect(reader.result.current.getSnapshot()).not.toHaveProperty("summary");
  });

  it("updates registered details and clears them when sharing is disabled by the page", () => {
    const { result, rerender } = renderHook(
      ({ details, enabled }: { details: AssistantPageDetails | null; enabled: boolean }) => {
        useRegisterAssistantPageContext(details, enabled);
        return useAssistantPageContext(route.path);
      },
      { initialProps: { details: detail() as AssistantPageDetails | null, enabled: true } },
    );
    expect(result.current.page.view).toBe("Week");
    rerender({ details: { ...detail(), view: "Month", selected_ids: ["job-2"] }, enabled: true });
    expect(result.current.getSnapshot()).toMatchObject({ view: "Month", selected_ids: ["job-2"] });
    rerender({ details: detail(), enabled: false });
    expect(result.current.getSnapshot()).not.toHaveProperty("view");
    rerender({ details: null, enabled: true });
    expect(result.current.getSnapshot()).not.toHaveProperty("resource");
  });

  it("detaches each submission from the registration and other snapshots", () => {
    const source = detail();
    renderHook(() => useRegisterAssistantPageContext(source));
    const { result } = renderHook(() => useAssistantPageContext(route.path));
    const first = result.current.getSnapshot();
    first.filters!.status = "changed";
    first.selected_ids!.push("job-2");
    source.filters!.status = "also changed";
    expect(result.current.getSnapshot()).toMatchObject({
      filters: { status: "pending" },
      selected_ids: ["job-1"],
    });
  });

  it("does not carry a registration through navigation before React catches up", () => {
    renderHook(() => useRegisterAssistantPageContext(detail()));
    const { result } = renderHook(() => useAssistantPageContext(route.path));
    const read = result.current.getSnapshot;
    window.history.replaceState({}, "", "/runs");
    const next = read();
    expect(next.path).toBe("/runs");
    expect(next).not.toHaveProperty("resource");
    expect(next).not.toHaveProperty("summary");
  });

  it.each(["account", "organization"] as const)(
    "drops old registered details when the %s changes, including a retained callback",
    (change) => {
      const originalScope = JSON.stringify([null, null]);
      useAssistantPageContextStore.getState().register({
        owner: "old-page",
        scope: originalScope,
        path: "/apps/scheduler",
        details: detail(),
      });
      const { result } = renderHook(() => useAssistantPageContext(route.path));
      const read = result.current.getSnapshot;
      expect(read().summary).toBe("One job is selected.");
      act(() => {
        if (change === "account")
          useAuthStore.setState({
            user: {
              id: "person-2",
              email: "person@example.test",
              is_active: true,
              created_at: "2026-01-01T00:00:00.000Z",
            },
          });
        else useOrgStore.setState({ activeOrgId: "organization-2" });
      });
      expect(result.current.page).not.toHaveProperty("resource");
      expect(read()).not.toHaveProperty("summary");
    },
  );

  it.each(["account", "organization"] as const)(
    "does not relabel a mounted provider's old details after an %s switch",
    (change) => {
      const provider = renderHook(() => useRegisterAssistantPageContext(detail()));
      const reader = renderHook(() => useAssistantPageContext(route.path));
      const read = reader.result.current.getSnapshot;
      expect(read().summary).toBe("One job is selected.");
      act(() => {
        if (change === "account")
          useAuthStore.setState({
            user: {
              id: "person-2",
              email: "person@example.test",
              is_active: true,
              created_at: "2026-01-01T00:00:00.000Z",
            },
          });
        else useOrgStore.setState({ activeOrgId: "organization-2" });
      });
      provider.rerender();
      expect(read()).not.toHaveProperty("resource");
      expect(reader.result.current.page).not.toHaveProperty("summary");

      // The page remounts its provider when data for the new scope is ready.
      provider.unmount();
      renderHook(() =>
        useRegisterAssistantPageContext({ ...detail(), summary: "A new account's view." }),
      );
      expect(read().summary).toBe("A new account's view.");
    },
  );

  it("reveals the still-mounted page registration after a temporary view closes", () => {
    const first = renderHook(() => useRegisterAssistantPageContext(detail()));
    const second = renderHook(() =>
      useRegisterAssistantPageContext({ ...detail(), view: "Selected job" }),
    );
    const reader = renderHook(() => useAssistantPageContext(route.path));
    expect(reader.result.current.page.view).toBe("Selected job");
    act(() => second.unmount());
    expect(reader.result.current.page.view).toBe("Week");
    act(() => first.unmount());
    expect(reader.result.current.page).not.toHaveProperty("view");
  });
});
