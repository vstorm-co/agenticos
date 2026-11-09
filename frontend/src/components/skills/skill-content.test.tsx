import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { SkillContent } from "./skill-content";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<SkillContent skillId="s1" versionId="v3" label="v3" />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("SkillContent", () => {
  it("reads the version the line serves, as the comparison reads one, with nothing marked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      id: "v3",
      number: 3,
      description: "How returns work",
      content: "Ask for the receipt first.",
      resources: [{ name: "policy.md", description: "The policy" }],
    });
    mount();

    expect(await screen.findByText("Ask for the receipt first.")).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/v3");
    expect(screen.getByText("How returns work")).toBeVisible();
    expect(screen.getByText("policy.md")).toBeVisible();
    expect(screen.getByText("v3")).toBeVisible();
    expect(screen.queryByText(/same as the reference/i)).toBeNull();
  });

  it("renders the instructions as Markdown, with the source one press away", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      id: "v3",
      number: 3,
      description: "How returns work",
      content: "# Returns\n\nAsk for the **receipt** first.",
      resources: [],
    });
    mount();

    expect(await screen.findByRole("heading", { name: "Returns" })).toBeVisible();
    expect(screen.getByText("receipt").tagName).toBe("STRONG");

    await userEvent.click(screen.getByRole("button", { name: /source/i }));

    expect(screen.queryByRole("heading", { name: "Returns" })).toBeNull();
    expect(screen.getByText("# Returns")).toBeVisible();
  });

  it("says when the version cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Boom", { error: { code: "INTERNAL", message: "Boom" } }),
    );
    mount();

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });
});
