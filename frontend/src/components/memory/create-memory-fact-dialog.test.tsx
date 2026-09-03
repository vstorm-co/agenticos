import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateMemoryFactDialog } from "./create-memory-fact-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-auth", () => ({ useAuth: vi.fn(() => ({ user: { id: "u-42" } })) }));

import { toast } from "sonner";
import { useAuth } from "@/hooks/use-auth";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const fact = () => screen.getByLabelText("Fact");
const create = () => screen.getByRole("button", { name: "Create" });
const scope = () => screen.getByLabelText("Scope");
const chooseScope = async (option: "Shared" | "Personal") => {
  await userEvent.click(scope());
  await userEvent.click(await screen.findByRole("option", { name: option }));
};

function mount(onOpenChange = vi.fn(), { canEdit = true } = {}) {
  render(
    <CreateMemoryFactDialog agentId="a1" open onOpenChange={onOpenChange} canEdit={canEdit} />,
    { wrapper },
  );
  return { onOpenChange };
}

describe("CreateMemoryFactDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuth).mockReturnValue({ user: { id: "u-42" } } as unknown as ReturnType<
      typeof useAuth
    >);
  });

  it("posts a shared fact under the agent", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "x1" });
    const { onOpenChange } = mount();

    await userEvent.type(fact(), "Acme FY starts in April");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith("/memory/facts", {
      agent_id: "a1",
      content: "Acme FY starts in April",
      end_user_scope_key: null,
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("writes to the operator's own personal store when personal is chosen", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "x1" });
    mount();

    await userEvent.type(fact(), "I prefer mornings");
    await chooseScope("Personal");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({
      end_user_scope_key: "user:u-42",
    });
  });

  it("lets an operator target another person's personal store", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "x1" });
    mount();

    await userEvent.type(fact(), "note");
    await chooseScope("Personal");
    const key = screen.getByLabelText("Whose personal store");
    await userEvent.clear(key);
    await userEvent.type(key, "user:someone-else");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({
      end_user_scope_key: "user:someone-else",
    });
  });

  it("gives a member no shared choice and writes only their own personal", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "x1" });
    mount(vi.fn(), { canEdit: false });

    expect(screen.queryByLabelText("Scope")).not.toBeInTheDocument();
    await userEvent.type(fact(), "note");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({
      end_user_scope_key: "user:u-42",
    });
  });

  it("cannot be submitted without content", () => {
    mount();
    expect(create()).toBeDisabled();
  });

  it("cannot save a personal fact with no signed-in person to attribute it to", async () => {
    vi.mocked(useAuth).mockReturnValue({ user: null } as unknown as ReturnType<typeof useAuth>);
    mount(vi.fn(), { canEdit: false });

    await userEvent.type(fact(), "note");
    expect(create()).toBeDisabled();
  });

  it("shows a field error the server named, cleared on edit", async () => {
    const problems = {
      error: {
        code: "VALIDATION_ERROR",
        message: "invalid",
        details: { fields: [{ field: "content", message: "must be text" }] },
      },
    };
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(422, "invalid", problems));
    const { onOpenChange } = mount();

    await userEvent.type(fact(), "note");
    await userEvent.click(create());

    await waitFor(() => expect(screen.getByText("must be text")).toBeInTheDocument());
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    await userEvent.type(fact(), "!");
    expect(screen.queryByText("must be text")).not.toBeInTheDocument();
  });

  it("toasts a failure that names no field", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("bad gateway"));
    mount();

    await userEvent.type(fact(), "note");
    await userEvent.click(create());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("closes without creating when cancelled", async () => {
    const { onOpenChange } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
