import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { SkillAgentList, SkillAgentUsage } from "@/types/skill-versions";
import { SkillAgents } from "./skill-agents";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push: vi.fn() }),
}));

function onMain(name: string, extra: Partial<SkillAgentUsage> = {}): SkillAgentUsage {
  return {
    agent: { id: name, name, slug: name.toLowerCase() },
    via_specialist: null,
    draft_only: false,
    binding: {
      state: "main",
      version: { id: "m12", number: 12, fork_id: null },
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

function mount(agents: SkillAgentList | undefined, error: unknown = null) {
  const onShow = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <SkillAgents
      skillId="s1"
      mainLatest={12}
      skillName="returns-policy"
      agents={agents}
      error={error}
      forks={[]}
      shown="all"
      onShow={onShow}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return { onShow };
}

const LIST = (items: SkillAgentUsage[]): SkillAgentList => ({
  main_latest: { id: "m12", number: 12 },
  items,
  hidden: 0,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

describe("SkillAgents", () => {
  it("names an environment and a draft that use another version", () => {
    mount(
      LIST([
        onMain("Support", {
          draft_differs: true,
          environments: [
            {
              id: "e1",
              name: "Staging",
              agent_version: 4,
              binding: {
                state: "pinned",
                version: { id: "m9", number: 9, fork_id: null },
                fork: null,
                behind_main: 3,
              },
            },
          ],
        }),
      ]),
    );

    expect(screen.getByText("Staging: v9 · pinned · 3 behind main")).toBeInTheDocument();
    expect(screen.getByText("Its draft uses a different version.")).toBeInTheDocument();
  });

  it("leaves a specialist's binding to the Builder", () => {
    mount(LIST([onMain("Support", { via_specialist: "Refunds helper" })]));

    expect(screen.getByText("Through its specialist Refunds helper")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Change the version/ })).toBeNull();
  });

  it("opens Change version for one agent and closes it again", async () => {
    mount(LIST([onMain("Support")]));

    await userEvent.click(
      screen.getByRole("button", { name: "Change the version of the skill for Support" }),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("Now: v12 · main");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("draws no count while the agents are on their way", () => {
    mount(undefined);
    expect(screen.queryByText("No agent here uses this skill.")).toBeNull();
    expect(screen.queryByRole("group", { name: "Which agents to show" })).toBeNull();
  });

  it("says when no agent uses the skill", () => {
    mount(LIST([]));
    expect(screen.getByText("No agent here uses this skill.")).toBeInTheDocument();
  });

  it("says when the agents cannot be read rather than showing none", () => {
    mount(undefined, new Error("offline"));
    expect(screen.queryByText("No agent here uses this skill.")).toBeNull();
    expect(screen.getByText("offline")).toBeInTheDocument();
  });
});
