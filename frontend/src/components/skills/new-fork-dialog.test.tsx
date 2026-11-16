import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { Skill } from "@/types/providers";
import type { SkillAgentUsage } from "@/types/skill-versions";
import { NewForkDialog } from "./new-fork-dialog";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SKILL = {
  id: "s1",
  name: "returns-policy",
  version: 5,
  latest_version_id: "m5",
  can_edit: true,
} as Skill;

function usage(name: string, extra: Partial<SkillAgentUsage> = {}): SkillAgentUsage {
  return {
    agent: { id: name.toLowerCase(), name, slug: name.toLowerCase() },
    via_specialist: null,
    draft_only: false,
    binding: {
      state: "main",
      version: { id: "m5", number: 5, fork_id: null },
      fork: null,
      behind_main: 0,
    },
    agent_version: 3,
    environments: [],
    draft_differs: false,
    can_change: true,
    can_publish: true,
    ...extra,
  };
}

function open(agents: SkillAgentUsage[]) {
  const onCreated = vi.fn();
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <NewForkDialog
      skill={SKILL}
      baseId="m5"
      agents={agents}
      onClose={onClose}
      onCreated={onCreated}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return { onCreated, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.post).mockResolvedValue({ id: "f9", name: "Marketplace" });
  vi.mocked(apiClient.put).mockResolvedValue({ published: true, environments: [] });
  vi.mocked(apiClient.get).mockResolvedValue({ latest_version_id: "m5", version: 5 });
});

describe("NewForkDialog", () => {
  it("starts a fork from main's newest version and moves the agents asked", async () => {
    const { onCreated } = open([
      usage("Desk"),
      usage("Counter"),
      usage("Helper", { draft_only: true }),
      usage("Billing", { via_specialist: "refunds" }),
      usage("Viewer", { can_change: false }),
    ]);

    expect(screen.getByText(/It starts from v5, main's newest version/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Helper/)).toBeNull();
    expect(screen.queryByLabelText(/Billing/)).toBeNull();
    expect(screen.queryByLabelText(/Viewer/)).toBeNull();
    const create = screen.getByRole("button", { name: "Create fork" });
    expect(create).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Name"), " Marketplace ");
    await userEvent.click(screen.getByLabelText("Desk · now v5 · main"));
    await userEvent.click(create);

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/forks", {
      name: "Marketplace",
      from_version_id: "m5",
    });
    expect(apiClient.put).toHaveBeenCalledTimes(1);
    expect(apiClient.put).toHaveBeenCalledWith("/skills/s1/agents/desk/binding", {
      state: "fork",
      fork_id: "f9",
    });
    expect(toast.success).toHaveBeenCalledWith(
      "Fork “Marketplace” created. 1 agent moved onto it.",
    );
    expect(onCreated).toHaveBeenCalledWith("f9");
  });

  it("names an agent that could not be moved, and still opens the fork", async () => {
    vi.mocked(apiClient.put).mockRejectedValue(
      new ApiError(403, "Forbidden", { error: { code: "FORBIDDEN", message: "Not yours" } }),
    );
    const { onCreated } = open([usage("Desk")]);

    await userEvent.type(screen.getByLabelText("Name"), "Marketplace");
    await userEvent.click(screen.getByLabelText(/Desk/));
    await userEvent.click(screen.getByLabelText(/Desk/));
    await userEvent.click(screen.getByLabelText(/Desk/));
    await userEvent.click(screen.getByRole("button", { name: "Create fork" }));

    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Desk was not moved"));
    expect(toast.success).toHaveBeenCalledWith("Fork “Marketplace” created.");
    expect(onCreated).toHaveBeenCalledWith("f9");
  });

  it("says why a fork was refused, and stays open", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(400, "Name taken"));
    const { onCreated } = open([]);

    expect(screen.getByText(/No agent can be moved onto it from here/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name"), "Marketplace");
    await userEvent.click(screen.getByRole("button", { name: "Create fork" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Name taken");
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("closes on Cancel and on Escape", async () => {
    const { onClose } = open([]);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("asks before moving an agent onto content it does not read now", async () => {
    open([
      usage("Desk", {
        binding: {
          state: "pinned",
          version: { id: "m2", number: 2, fork_id: null },
          fork: null,
          behind_main: 3,
        },
      }),
    ]);

    await userEvent.type(screen.getByLabelText("Name"), "Marketplace");
    await userEvent.click(screen.getByLabelText(/Desk · now/));
    const create = screen.getByRole("button", { name: "Create fork" });
    expect(create).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/Desk reads another version now/));
    expect(create).toBeEnabled();
  });

  it("starts from a main saved since it opened, after saying so", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ latest_version_id: "m6", version: 6 });
    open([]);

    await userEvent.type(screen.getByLabelText("Name"), "Marketplace");
    await userEvent.click(screen.getByRole("button", { name: "Create fork" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Main has a newer version, v6");
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.getByText(/It starts from v6/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create fork" }));
    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/forks", {
      name: "Marketplace",
      from_version_id: "m6",
    });
  });
});
