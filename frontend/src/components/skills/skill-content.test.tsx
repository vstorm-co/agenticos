import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { SkillContent } from "./skill-content";
import { browserProcedureFixture } from "@/test-utils/browser-teaching";
// This file verifies rich Markdown, so load the real lazy chunk before its render assertions.
import "@/components/chat/markdown-content.impl";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<SkillContent skillId="s1" versionId="v3" label="v3" />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("SkillContent", () => {
  it.each([
    ["manual", false, "This is a human demonstration."],
    ["refinement", true, "The browser reported Done and the agent run completed."],
    ["refinement", false, "This suggestion is not reviewable until the browser"],
  ] as const)(
    "qualifies the exact teaching version's %s evidence (%s)",
    async (source, verified, message) => {
      vi.mocked(apiClient.get).mockResolvedValue({
        id: "v3",
        number: 3,
        source: "browser_teaching",
        description: "Reviewed procedure",
        content: "Review the monthly report.",
        resources: [],
        browser_procedure: browserProcedureFixture({ source, verified_success: verified }),
      });
      mount();
      const summary = await screen.findByRole("region", { name: "Browser procedure" });
      expect(summary).toHaveTextContent("https://reports.example");
      expect(summary).toHaveTextContent(message);
      expect(summary).toHaveTextContent("does not authorize replay");
      expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/v3");
    },
  );

  it("does not carry teaching provenance onto a later ordinary edit or restore", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => ({
      id: path.endsWith("v3") ? "v3" : "v4",
      number: path.endsWith("v3") ? 3 : 4,
      source: path.endsWith("v3") ? "browser_teaching" : "restore",
      description: "Reviewed procedure",
      content: path.endsWith("v3") ? "Original teaching instructions." : "Restored instructions.",
      resources: [],
      // Even a malformed older response must not turn a non-teaching version into provenance.
      browser_procedure: browserProcedureFixture(),
    }));
    const view = mount();
    expect(await screen.findByRole("region", { name: "Browser procedure" })).toBeVisible();
    view.rerender(<SkillContent skillId="s1" versionId="v4" label="v4" />);
    expect(await screen.findByText("Restored instructions.")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Browser procedure" })).toBeNull();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/v4");
  });

  it("reads a teaching version that has no procedure metadata without inventing it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      id: "v3",
      number: 3,
      source: "browser_teaching",
      description: "Metadata unavailable",
      content: "Reviewed instructions.",
      resources: [],
      browser_procedure: null,
    });
    mount();
    expect(await screen.findByText("Reviewed instructions.")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Browser procedure" })).toBeNull();
  });

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
