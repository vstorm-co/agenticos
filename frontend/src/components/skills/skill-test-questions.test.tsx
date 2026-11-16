import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { SkillTestQuestions } from "./skill-test-questions";

const permissions = vi.hoisted(() => ({ datasetsEdit: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permissions.datasetsEdit, isLoading: false }),
}));

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function mount(canCreate = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<SkillTestQuestions skillId="k1" canCreate={canCreate} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => window.history.replaceState(null, "", "/"));

describe("SkillTestQuestions", () => {
  it("counts the questions and links to their dataset", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      id: "ts",
      name: "returns · test questions",
      case_count: 10,
    });
    mount();

    expect(
      await screen.findByRole("link", { name: "Open returns · test questions" }),
    ).toHaveAttribute("href", "/datasets/ts");
    expect(screen.getByText("10 questions")).toBeVisible();
  });

  it("starts them from recent answers through one control", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "None"));
    vi.mocked(apiClient.post).mockResolvedValue({ id: "ts", case_count: 0 });
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add test questions" }));
    expect(apiClient.post).toHaveBeenLastCalledWith("/skills/k1/test-set", {
      from_evidence: true,
    });
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("offers nothing to start to a reader who may not write them", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "None"));
    mount(false);

    expect(
      await screen.findByText("Someone who may edit this skill and create datasets can add them."),
    ).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says what refused writing them, but not that somebody wrote them meanwhile", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "None"));
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new ApiError(409, "Already exists"))
      .mockRejectedValueOnce(
        new ApiError(400, "No access", { error: { code: "VALIDATION", message: "No access" } }),
      );
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Add test questions" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Add test questions" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("No access"));
  });

  it("says the skill has questions in a dataset the reader may not open, offering none", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(403, "Hidden", {
        error: { code: "FORBIDDEN", message: "Hidden", details: { reason: "test_set_hidden" } },
      }),
    );
    mount();

    expect(
      await screen.findByText("This skill has test questions, in a dataset you may not open."),
    ).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says when they cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Boom", { error: { code: "INTERNAL", message: "Boom" } }),
    );
    mount();

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });

  it("scrolls to itself when the address points at it", async () => {
    window.history.replaceState(null, "", "/skills/k1#test-questions");
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "None"));
    mount();

    await waitFor(() => expect(scrolled).toHaveBeenCalled());
  });
});
