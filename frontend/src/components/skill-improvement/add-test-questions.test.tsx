import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { AddTestQuestions } from "./add-test-questions";

const permissions = vi.hoisted(() => ({ datasetsEdit: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permissions.datasetsEdit, isLoading: false }),
}));

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<AddTestQuestions skillId="k1" />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.datasetsEdit = true;
});

describe("AddTestQuestions", () => {
  it("links to the skill's questions when it has them", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "ts", case_count: 10 });
    mount();

    expect(
      await screen.findByRole("link", { name: "The skill has 10 test questions" }),
    ).toHaveAttribute("href", "/datasets/ts");
  });

  it("writes them when there are none, and shows them after", async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new ApiError(404, "None"))
      .mockResolvedValue({ id: "ts", case_count: 8 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "ts", case_count: 8 });
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add test questions" }));

    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/test-set", { from_evidence: true });
    expect(
      await screen.findByRole("link", { name: "The skill has 8 test questions" }),
    ).toBeVisible();
  });

  it("takes somebody else's questions written meanwhile without an error", async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new ApiError(404, "None"))
      .mockResolvedValue({ id: "ts", case_count: 5 });
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(409, "Already exists"));
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add test questions" }));

    expect(
      await screen.findByRole("link", { name: "The skill has 5 test questions" }),
    ).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says what refused writing them", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "None"));
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "No access", { error: { code: "VALIDATION", message: "No access" } }),
    );
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add test questions" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("No access"));
  });

  it("says when the questions cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Boom", { error: { code: "INTERNAL", message: "Boom" } }),
    );
    mount();

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });

  it("offers no way to write them to somebody who may not create datasets", async () => {
    permissions.datasetsEdit = false;
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "None"));
    mount();

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    // Past loading: the refusal is the permission, not the read still pending.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
