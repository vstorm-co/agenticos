import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentTemplateDialog } from "./agent-template-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CATALOG = {
  industries: [
    {
      id: "healthcare",
      templates: [
        {
          key: "healthcare/procedure-assistant",
          name: "Procedure Assistant",
          description: "Answers staff from your SOPs.",
          capabilities: ["knowledge", "clock", "future_cap"],
          skills: ["healthcare/clinical-procedure-lookup"],
          mcp: ["github", "acme-crm"],
          attach: ["collection"],
          budget_usd: 50,
          installed: false,
        },
        {
          key: "healthcare/patient-front-desk",
          name: "Patient Front Desk",
          description: "Handles administrative questions.",
          capabilities: [],
          skills: [],
          mcp: [],
          attach: [],
          budget_usd: null,
          installed: true,
        },
      ],
    },
    // No icon in the table, to prove the fallback rather than a blank card.
    { id: "aerospace", templates: [] },
  ],
};

const MCP_CATALOG = {
  items: [{ key: "github", name: "GitHub", icon: "github" }],
  total: 1,
};

const INSTALLED = {
  agent_id: "11111111-1111-1111-1111-111111111111",
  slug: "procedure-assistant",
  name: "Procedure Assistant",
  skills_installed: ["Clinical procedure lookup"],
  attach: ["collection"],
  suggested_mcp: ["github"],
};

function open() {
  return render(<AgentTemplateDialog open onOpenChange={vi.fn()} ceiling={null} />, { wrapper });
}

describe("AgentTemplateDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/agents/mcp-catalog" ? MCP_CATALOG : CATALOG,
    );
    vi.mocked(apiClient.post).mockResolvedValue(INSTALLED);
  });

  it("does not fetch the catalog until the dialog is open", () => {
    render(<AgentTemplateDialog open={false} onOpenChange={vi.fn()} ceiling={null} />, { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("shows a card per industry with how many templates it holds", async () => {
    open();
    expect(await screen.findByText("Healthcare")).toBeInTheDocument();
    expect(screen.getByText("2 agents")).toBeInTheDocument();
    expect(screen.getByText("0 agents")).toBeInTheDocument();
  });

  it("says what a template brings and what is still missing", async () => {
    open();
    await userEvent.click(await screen.findByText("Healthcare"));

    expect(screen.getByText("Procedure Assistant")).toBeInTheDocument();
    // A capability by the name the Toolbox gives it, never its registry id.
    expect(screen.getByText("Knowledge search")).toBeInTheDocument();
    expect(screen.queryByText("knowledge")).not.toBeInTheDocument();
    // One the console has no words for yet shows the registry's id.
    expect(screen.getByText("future_cap")).toBeInTheDocument();
    expect(screen.getByText("50 USD / month")).toBeInTheDocument();
    expect(screen.getByText("Installs 1 skill with it")).toBeInTheDocument();
    expect(screen.getByText("Works well with")).toBeInTheDocument();
    // A server by its catalog name once the catalog answers.
    expect(await screen.findByText("GitHub")).toBeInTheDocument();
    // One the catalog does not hold keeps its key rather than vanishing.
    expect(screen.getByText("acme-crm")).toBeInTheDocument();
  });

  it("offers no button for one the organization already has", async () => {
    open();
    await userEvent.click(await screen.findByText("Healthcare"));

    expect(screen.getByText("Installed")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Use this" })).toHaveLength(1);
  });

  it("says the organization is at its agent limit instead of offering a refused install", async () => {
    // Installing creates an agent, so at the limit every install is refused (#2488).
    render(<AgentTemplateDialog open onOpenChange={vi.fn()} ceiling={{ limit: 5, held: 5 }} />, {
      wrapper,
    });
    await userEvent.click(await screen.findByText("Healthcare"));

    expect(screen.getByText("This organization is at its agent limit")).toBeInTheDocument();
    expect(
      screen.getByText(/allows 5 agents per organization, and this one has 5/),
    ).toBeInTheDocument();
    const use = screen.getByRole("button", { name: "Use this" });
    expect(use).toBeDisabled();
    await userEvent.click(use);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("installs a template and opens the draft in the Builder", async () => {
    const onOpenChange = vi.fn();
    render(<AgentTemplateDialog open onOpenChange={onOpenChange} ceiling={null} />, { wrapper });
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Use this" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/agents/templates/install", {
        key: "healthcare/procedure-assistant",
      }),
    );
    // Straight to the Builder, because the draft still needs a model.
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/agents/11111111-1111-1111-1111-111111111111"),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(toast.success).toHaveBeenCalledWith(
      "Procedure Assistant created as a draft - pick a model, then publish",
    );
  });

  it("shows the install in flight rather than a dead button", async () => {
    let release: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Use this" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Use this" })).not.toBeInTheDocument(),
    );
    release(INSTALLED);
  });

  it("surfaces a refusal instead of failing silently", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "Taken", {
        error: { code: "ALREADY_EXISTS", message: "Taken", details: {} },
      }),
    );
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "Use this" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(push).not.toHaveBeenCalled();
  });

  it("goes back to the shelves", async () => {
    open();
    await userEvent.click(await screen.findByText("Healthcare"));
    await userEvent.click(screen.getByRole("button", { name: "All industries" }));

    expect(screen.getByText("Agent templates")).toBeInTheDocument();
  });

  it("forgets which industry was open when the dialog closes", async () => {
    const onOpenChange = vi.fn();
    render(<AgentTemplateDialog open onOpenChange={onOpenChange} ceiling={null} />, { wrapper });
    await userEvent.click(await screen.findByText("Healthcare"));

    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(screen.getByText("Agent templates")).toBeInTheDocument();
  });

  it("renders an error state rather than an empty catalog", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("down"));
    open();

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("Healthcare")).not.toBeInTheDocument();
  });
});
