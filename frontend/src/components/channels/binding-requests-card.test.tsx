import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BindingRequestsCard } from "./binding-requests-card";
import { apiClient } from "@/lib/api-client";
import type { BindingRequest } from "@/types/channels";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
let mayManage = true;
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => mayManage, isLoading: false }),
}));
let requested = "";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(requested),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function request(overrides: Partial<BindingRequest> = {}): BindingRequest {
  return {
    id: "r1",
    kind: "bind",
    status: "pending",
    void_reason: null,
    agent_id: "a1",
    agent_name: "Front desk",
    channel_bot_id: "b1",
    channel_bot_name: "Shop line",
    exposure_id: null,
    environment_id: null,
    session_scope: null,
    requester_user_id: "u1",
    requester_email: "ana@example.com",
    note: "For the shop",
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-11-04T09:00:00Z",
    ...overrides,
  };
}

let queue: BindingRequest[];

beforeEach(() => {
  vi.clearAllMocks();
  mayManage = true;
  requested = "";
  queue = [request()];
  vi.mocked(apiClient.get).mockImplementation(async () => ({ items: queue, total: queue.length }));
  vi.mocked(apiClient.post).mockImplementation(async () => {
    queue = [];
    return request({ status: "approved" });
  });
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe("the binding requests card", () => {
  it("shows nothing to somebody who cannot decide, and asks nothing of the server", () => {
    mayManage = false;
    render(<BindingRequestsCard />, { wrapper });

    expect(screen.queryByText("Binding requests")).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("shows nothing when nothing waits", async () => {
    queue = [];
    render(<BindingRequestsCard />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(screen.queryByText("Binding requests")).not.toBeInTheDocument();
  });

  it("says who asks for what, with their note", async () => {
    render(<BindingRequestsCard />, { wrapper });

    expect(
      await screen.findByText("ana@example.com asks to bind Front desk to Shop line"),
    ).toBeInTheDocument();
    expect(screen.getByText("Note: For the shop")).toBeInTheDocument();
  });

  it("words an environment change and a resume as what they are", async () => {
    queue = [
      request({ id: "r2", kind: "environment", note: null }),
      request({ id: "r3", kind: "resume", note: null }),
    ];
    render(<BindingRequestsCard />, { wrapper });

    expect(
      await screen.findByText(
        "ana@example.com asks to change the environment of Front desk on Shop line",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("ana@example.com asks to resume Front desk on Shop line"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Note:/)).not.toBeInTheDocument();
  });

  it("approves, and the list refreshes without it", async () => {
    render(<BindingRequestsCard />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    expect(apiClient.post).toHaveBeenCalledWith("/channels/binding-requests/r1/approve", {});
    await waitFor(() => expect(screen.queryByText(/asks to bind/)).not.toBeInTheDocument());
  });

  it("declines", async () => {
    render(<BindingRequestsCard />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: "Decline" }));

    expect(apiClient.post).toHaveBeenCalledWith("/channels/binding-requests/r1/decline", {});
  });

  it("scrolls into view when the link says requests=open", async () => {
    requested = "requests=open";
    render(<BindingRequestsCard />, { wrapper });

    await screen.findByText("Binding requests");

    await waitFor(() => expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalled());
  });
});
