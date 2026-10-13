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
          capabilities: ["knowledge", "clock"],
          skills: ["healthcare/clinical-procedure-lookup"],
          mcp: ["github"],
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

const INSTALLED = {
  agent_id: "11111111-1111-1111-1111-111111111111",
  slug: "procedure-assistant",
  name: "Procedure Assistant",
  skills_installed: ["Clinical procedure lookup"],
  attach: ["collection"],
  suggested_mcp: ["github"],
};

function open() {
  return render(<AgentTemplateDialog open onOpenChange={vi.fn()} />, { wrapper });
}

describe("AgentTemplateDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(CATALOG);
    vi.mocked(apiClient.post).mockResolvedValue(INSTALLED);
  });

  it("does not fetch the catalog until the dialog is open", () => {
    render(<AgentTemplateDialog open={false} onOpenChange={vi.fn()} />, { wrapper });
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
    expect(screen.getByText("knowledge")).toBeInTheDocument();
    expect(screen.getByText("50 USD / month")).toBeInTheDocument();
    expect(screen.getByText("Installs 1 skill with it")).toBeInTheDocument();
    // The honest line: it arrives as a draft and this is what it lacks.
    expect(screen.getByText("You still attach: collection")).toBeInTheDocument();
    expect(screen.getByText("Works well with: github")).toBeInTheDocument();
  });

  it("offers no button for one the organization already has", async () => {
    open();
    await userEvent.click(await screen.findByText("Healthcare"));

    expect(screen.getByText("Installed")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Use this" })).toHaveLength(1);
  });

  it("installs a template and opens the draft in the Builder", async () => {
    const onOpenChange = vi.fn();
    render(<AgentTemplateDialog open onOpenChange={onOpenChange} />, { wrapper });
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
      "Procedure Assistant created as a draft — pick a model, then publish",
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
    render(<AgentTemplateDialog open onOpenChange={onOpenChange} />, { wrapper });
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
