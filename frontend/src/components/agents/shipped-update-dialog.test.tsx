import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ShippedAgentUpdate } from "@/lib/shipped-agent-api";
import { ShippedUpdateDialog } from "./shipped-update-dialog";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

const UPDATE: ShippedAgentUpdate = {
  revision: "reviewed-revision",
  changes: [
    { version: "draft", field: "instructions", before: "Previous draft", after: "New draft" },
    { version: "published", field: "instructions", before: "Previous live", after: "New live" },
  ],
};

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset().mockResolvedValue(UPDATE);
  vi.mocked(apiClient.post).mockReset().mockResolvedValue(null);
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const close = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ShippedUpdateDialog agentId="agent-1" onClose={close} />
    </QueryClientProvider>,
  );
  return { close, invalidate };
}

it("announces loading without offering an unreviewed update and permits dismissal", async () => {
  vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
  const { close } = mount();
  expect(screen.getByRole("status", { name: "Loading" })).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByRole("button", { name: "Apply built-in update" })).toBeNull();
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledOnce();
  expect(apiClient.post).not.toHaveBeenCalled();
});

it("shows a preview failure rather than describing the agent as current", async () => {
  vi.mocked(apiClient.get).mockRejectedValue(new Error("Preview unavailable"));
  mount();
  expect(await screen.findByText("Preview unavailable")).toBeVisible();
  expect(screen.queryByText("Already using the built-in defaults.")).toBeNull();
  expect(apiClient.post).not.toHaveBeenCalled();
});

it("has nothing to apply when the reviewed version is already current", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ revision: "current", changes: [] });
  mount();
  expect(await screen.findByText("Already using the built-in defaults.")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Apply built-in update" })).toBeNull();
});

it("applies exactly the displayed revision and refreshes agents and environments", async () => {
  const { close, invalidate } = mount();
  expect(await screen.findByRole("heading", { name: "Draft · instructions" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Published · instructions" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Apply built-in update" }));
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
  expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/shipped-update");
  expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/shipped-update", {
    expected_revision: UPDATE.revision,
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.agents.all() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.environments.list("agent-1") });
});

it("requires another review after a refused update instead of retrying a stale revision", async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("The draft changed"));
  const { close } = mount();
  await userEvent.click(await screen.findByRole("button", { name: "Apply built-in update" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The draft changed");
  expect(screen.getByRole("button", { name: "Apply built-in update" })).toBeDisabled();
  expect(close).not.toHaveBeenCalled();
  vi.mocked(apiClient.get).mockResolvedValue({ ...UPDATE, revision: "fresh-revision" });
  await userEvent.click(screen.getByRole("button", { name: "Reload diff" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply built-in update" })).toBeEnabled(),
  );
  await userEvent.click(screen.getByRole("button", { name: "Apply built-in update" }));
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/agent-1/shipped-update", {
    expected_revision: "fresh-revision",
  });
});

it("keeps the reviewed dialog open while publication is pending", async () => {
  let finish: (value: null) => void = () => {
    throw new Error("Update has not started");
  };
  vi.mocked(apiClient.post).mockReturnValue(
    new Promise<null>((resolve) => {
      finish = resolve;
    }),
  );
  const { close } = mount();
  await userEvent.click(await screen.findByRole("button", { name: "Apply built-in update" }));
  await userEvent.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Apply built-in update" })).toBeDisabled();
  finish(null);
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
});
