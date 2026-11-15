import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Trigger } from "@/types/triggers";
import { TriggerFormDialog } from "./trigger-form-dialog";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

const native = vi.hoisted(() => ({ allow: vi.fn(), pick: vi.fn(), grants: [] as unknown[] }));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/hooks/use-routine-local-work", () => ({
  useRoutineLocalWork: () => ({
    available: true,
    supportsWrites: true,
    identity: { device_id: "device", user_id: "owner", origin: "https://example.com" },
    org: "org",
    user: "owner",
    allow: { mutateAsync: native.allow },
    grants: { data: native.grants },
    pick: {
      isPending: false,
      mutate: (_input: undefined, options: { onSuccess: (folder: string) => void }) =>
        options.onSuccess("/work"),
    },
  }),
}));
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const approved = {
  folder: "/work",
  mode: "read_only",
  device_id: "device",
  routine_grant: "grant",
  operations: { read: true, write: false, execute: false },
};
beforeEach(() => {
  vi.clearAllMocks();
  native.grants = [];
  useOrgStore.setState({ activeOrgId: "org" });
  useAuthStore.setState({
    user: {
      id: "owner",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
    },
  });
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path === "/me/permissions" ? { permissions: [] } : { items: [], total: 0 },
  );
  vi.mocked(apiClient.post).mockResolvedValue({
    id: "routine",
    trigger_type: "schedule",
    is_active: false,
  });
  vi.mocked(apiClient.patch).mockResolvedValue({
    id: "routine",
    trigger_type: "schedule",
    is_active: true,
  });
  native.allow.mockResolvedValue(approved);
});
async function configure() {
  const user = userEvent.setup();
  const onCreated = vi.fn();
  const onOpenChange = vi.fn();
  const view = render(
    <TriggerFormDialog agentId="agent" open onOpenChange={onOpenChange} onCreated={onCreated} />,
    { wrapper },
  );
  const dialog = within(await screen.findByRole("dialog"));
  await user.click(dialog.getByRole("checkbox", { name: /Run as me/ }));
  await user.click(dialog.getByRole("button", { name: /Choose a folder/ }));
  await user.click(dialog.getByRole("button", { name: "Continue" }));
  fireEvent.change(dialog.getByLabelText("Message"), { target: { value: "Read the report" } });
  await user.click(dialog.getByRole("button", { name: "Continue" }));
  return { user, dialog, onCreated, onOpenChange, ...view };
}
describe("local routine creation", () => {
  it("creates paused, asks once for every routine, then attaches and activates", async () => {
    const { user, dialog, onCreated } = await configure();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent/triggers",
      expect.objectContaining({ is_active: false, runs_as_creator: true }),
    );
    expect(vi.mocked(apiClient.post).mock.calls[0]?.[1]).not.toHaveProperty("local_target");
    expect(native.allow).toHaveBeenCalledWith(
      expect.objectContaining({
        routine_id: null,
        organization_id: "org",
        user_id: "owner",
        device_id: "device",
        root: "/work",
        operations: approved.operations,
      }),
    );
    expect(apiClient.patch).toHaveBeenCalledWith("/agents/agent/triggers/routine", {
      local_target: approved,
      is_active: true,
    });
  });
  it("uses the permission for every routine without asking again", async () => {
    native.grants = [
      {
        id: "all",
        routine_id: null,
        root: "/",
        operations: { read: true, write: true, execute: true },
      },
    ];
    const { user, dialog, onCreated } = await configure();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(native.allow).not.toHaveBeenCalled();
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/agents/agent/triggers/routine",
      expect.objectContaining({
        local_target: expect.objectContaining({ routine_grant: "all", folder: "/work" }),
        is_active: true,
      }),
    );
  });
  it("keeps cancellation paused and retries the same routine without duplicates", async () => {
    native.allow.mockResolvedValueOnce(null);
    const { user, dialog, onCreated } = await configure();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(native.allow).toHaveBeenCalledTimes(1));
    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(native.allow).toHaveBeenCalledTimes(2);
  });
  it("reuses native consent when the attach request fails", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error("connection lost"));
    const { user, dialog, onCreated } = await configure();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(native.allow).toHaveBeenCalledTimes(1);
    expect(apiClient.patch).toHaveBeenCalledTimes(2);
  });
  it("does not activate after an organization switch during native confirmation", async () => {
    let finish: (value: typeof approved) => void = () => {
      throw new Error("not opened");
    };
    native.allow.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { user, dialog, onCreated } = await configure();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(native.allow).toHaveBeenCalledTimes(1));
    await act(async () => {
      useOrgStore.setState({ activeOrgId: "another" });
      finish(approved);
    });
    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    expect(native.allow).toHaveBeenCalledTimes(1);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("does not activate after closing the containing page", async () => {
    let finish: (value: typeof approved) => void = () => {
      throw new Error("not opened");
    };
    native.allow.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { user, dialog, unmount } = await configure();
    await user.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(native.allow).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => {
      finish(approved);
    });
    expect(apiClient.patch).not.toHaveBeenCalled();
  });
});

it.each([false, true])(
  "reviews a changed folder target only when its permissions remain changed (%s)",
  async (changed) => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const localTarget = {
      operations: { execute: false, write: false, read: true },
      routine_grant: "grant",
      device_id: "device",
      mode: "read_only" as const,
      folder: "/work",
    };
    const trigger: Trigger = {
      id: "routine",
      agent_id: "agent",
      agent_name: null,
      name: "Report",
      created_by_user_id: "owner",
      is_active: true,
      can_manage: true,
      environment_id: null,
      runs_as_creator: true,
      trigger_type: "schedule",
      schedule_kind: "interval",
      interval_seconds: 3600,
      cron_expression: null,
      time_zone: null,
      overlap: "skip",
      event_source: null,
      event_config: {},
      prompt: "Read the report",
      next_fire_at: null,
      last_fired_at: null,
      last_run_id: null,
      conversation_id: null,
      webhook_url: null,
      created_at: null,
      updated_at: null,
      local_target: localTarget,
    };
    render(
      <TriggerFormDialog agentId="agent" trigger={trigger} open onOpenChange={onOpenChange} />,
      {
        wrapper,
      },
    );
    const dialog = within(await screen.findByRole("dialog"));
    // Local work lives in the routine's existing advanced options.
    await user.click(dialog.getByText("Advanced options", { exact: true }));
    const write = dialog.getByRole("checkbox", { name: "Write" });
    await user.click(write);
    if (!changed) await user.click(write);
    else
      native.allow.mockResolvedValue({
        ...approved,
        mode: "workspace_write",
        routine_grant: "new-grant",
        operations: { read: true, write: true, execute: false },
      });
    fireEvent.change(dialog.getByLabelText("Message"), {
      target: { value: "Read the updated report" },
    });
    await user.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    const body = vi.mocked(apiClient.patch).mock.calls[0]?.[1];
    if (changed) {
      expect(native.allow).toHaveBeenCalledOnce();
      expect(native.allow).toHaveBeenCalledWith(
        expect.objectContaining({ operations: { read: true, write: true, execute: false } }),
      );
      expect(body).toHaveProperty("local_target.routine_grant", "new-grant");
    } else {
      expect(native.allow).not.toHaveBeenCalled();
      expect(body).not.toHaveProperty("local_target");
    }
  },
);
