import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useOrganizations } from "@/hooks/use-organizations";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import { StartTeamRoom } from "./start-team-room";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const push = vi.fn();
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const account = (id = "me") => ({
  id,
  email: `${id}@example.com`,
  is_active: true,
  created_at: "2026-11-13T00:00:00Z",
});
const organization = { id: "org-a", name: "Our organization", is_personal: true };
const room = { id: "new-room", project_id: "project-a" };
let client: QueryClient;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function InitializingRoom() {
  useOrganizations();
  return <StartTeamRoom projectId="project-a" />;
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  useAuthStore.setState({ user: account() });
  useOrgStore.setState({ activeOrgId: "org-a", refusedOrgIds: [] });
  vi.mocked(apiClient.get).mockResolvedValue({ items: [organization] });
  vi.mocked(apiClient.post).mockResolvedValue(room);
});
afterEach(() => client.clear());

describe("starting a team room", () => {
  it("admits one rapid pair of click events before the disabled state is painted", async () => {
    const creation = deferred<typeof room>();
    vi.mocked(apiClient.post).mockReturnValueOnce(creation.promise);
    render(<StartTeamRoom projectId="project-a" />, { wrapper });
    const button = screen.getByRole("button", { name: "New team room" });
    act(() => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    expect(button).toBeDisabled();
    await act(async () => creation.resolve(room));
    expect(push).toHaveBeenCalledExactlyOnceWith("/chat?id=new-room");
  });

  it("waits for the signed-in account before allowing creation", async () => {
    useAuthStore.setState({ user: null });
    render(<StartTeamRoom projectId="project-a" />, { wrapper });
    const button = screen.getByRole("button", { name: "New team room" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(apiClient.post).not.toHaveBeenCalled();

    act(() => useAuthStore.setState({ user: account() }));
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat?id=new-room"));
  });

  it("waits for deferred organization selection, then opens the newly created room", async () => {
    useOrgStore.setState({ activeOrgId: null });
    const organizations = deferred<{ items: (typeof organization)[] }>();
    const creation = deferred<typeof room>();
    vi.mocked(apiClient.get).mockReturnValue(organizations.promise);
    const submittedOrganizations: (string | null)[] = [];
    vi.mocked(apiClient.post).mockImplementation(() => {
      submittedOrganizations.push(useOrgStore.getState().activeOrgId);
      return creation.promise;
    });
    render(<InitializingRoom />, { wrapper });
    const button = screen.getByRole("button", { name: "New team room" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(apiClient.post).not.toHaveBeenCalled();

    await act(async () => organizations.resolve({ items: [organization] }));
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    fireEvent.click(button);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(apiClient.post).toHaveBeenCalledWith("/conversations", {
      project_id: "project-a",
      title: expect.any(String),
    });
    expect(submittedOrganizations).toEqual(["org-a"]);
    expect(button).toBeDisabled();
    expect(push).not.toHaveBeenCalled();

    await act(async () => creation.resolve(room));
    expect(push).toHaveBeenCalledExactlyOnceWith("/chat?id=new-room");
  });

  it("keeps creation disabled when the fallback tenant is known but selection is pending", async () => {
    useOrgStore.setState({ activeOrgId: null });
    client.setQueryData(qk.organizations.list(), [organization]);
    render(<StartTeamRoom projectId="project-a" />, { wrapper });
    const button = screen.getByRole("button", { name: "New team room" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(apiClient.post).not.toHaveBeenCalled();

    act(() => useOrgStore.setState({ activeOrgId: "org-a" }));
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat?id=new-room"));
  });

  it.each(["account", "organization", "unmount"] as const)(
    "does not navigate or invalidate after the %s changes during creation",
    async (boundary) => {
      const creation = deferred<typeof room>();
      vi.mocked(apiClient.post).mockReturnValue(creation.promise);
      const invalidate = vi.spyOn(client, "invalidateQueries");
      const view = render(<StartTeamRoom projectId="project-a" />, { wrapper });
      fireEvent.click(screen.getByRole("button", { name: "New team room" }));
      expect(apiClient.post).toHaveBeenCalledTimes(1);

      act(() => {
        if (boundary === "account") useAuthStore.setState({ user: account("other") });
        if (boundary === "organization") useOrgStore.setState({ activeOrgId: "org-b" });
        if (boundary === "unmount") view.unmount();
      });
      await act(async () => creation.resolve(room));
      expect(push).not.toHaveBeenCalled();
      expect(invalidate).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
    },
  );

  it("shows a current creation failure and allows another attempt", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Creation failed"));
    render(<StartTeamRoom projectId="project-a" />, { wrapper });
    const button = screen.getByRole("button", { name: "New team room" });
    fireEvent.click(button);
    await waitFor(() => expect(toast.error).toHaveBeenCalledExactlyOnceWith(expect.any(String)));
    expect(button).toBeEnabled();
    expect(push).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat?id=new-room"));
    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });

  it.each(["account", "organization", "unmount"] as const)(
    "does not report a late creation failure after the %s changes",
    async (boundary) => {
      const creation = deferred<typeof room>();
      vi.mocked(apiClient.post).mockReturnValue(creation.promise);
      const view = render(<StartTeamRoom projectId="project-a" />, { wrapper });
      fireEvent.click(screen.getByRole("button", { name: "New team room" }));
      act(() => {
        if (boundary === "account") useAuthStore.setState({ user: account("other") });
        if (boundary === "organization") useOrgStore.setState({ activeOrgId: "org-b" });
        if (boundary === "unmount") view.unmount();
      });
      await act(async () => creation.reject(new Error("Old request failed")));
      expect(push).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
    },
  );
});
