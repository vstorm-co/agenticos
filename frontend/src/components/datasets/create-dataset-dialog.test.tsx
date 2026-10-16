import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { CreateDatasetDialog } from "./create-dataset-dialog";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount() {
  const onOpenChange = vi.fn();
  const onCreated = vi.fn();
  render(<CreateDatasetDialog open onOpenChange={onOpenChange} onCreated={onCreated} />, {
    wrapper,
  });
  return { onOpenChange, onCreated };
}

describe("CreateDatasetDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("creates a dataset, trimming what was typed, and hands it back", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "d1", name: "refunds" });
    const { onOpenChange, onCreated } = mount();
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/^Name/), " refunds ");
    await userEvent.type(screen.getByLabelText("Description"), " returns ");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: "d1", name: "refunds" }));
    expect(apiClient.post).toHaveBeenCalledWith("/datasets", {
      name: "refunds",
      description: "returns",
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says a taken name under the name, and sends no description when none was written", async () => {
    const taken = "A dataset named 'refunds' already exists.";
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, taken, {
        error: { code: "ALREADY_EXISTS", message: taken, details: { name: "refunds" } },
      }),
    );
    mount();
    await userEvent.type(screen.getByLabelText(/^Name/), "refunds");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(taken)).toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledWith("/datasets", {
      name: "refunds",
      description: null,
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("toasts a refusal that names no field", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("down"));
    mount();
    await userEvent.type(screen.getByLabelText(/^Name/), "refunds");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("closes on cancel", async () => {
    const { onOpenChange } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
