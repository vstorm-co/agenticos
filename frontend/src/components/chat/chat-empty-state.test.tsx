import { renderToString } from "react-dom/server";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatEmptyState, greetingKey } from "./chat-empty-state";
import type { Agent } from "@/types/agents";

const env = vi.hoisted(() => ({
  agents: [] as Partial<Agent>[],
  loading: false,
  personalLoading: false,
  personal: null as string[] | null,
}));

vi.mock("@/hooks", () => ({
  useAuth: () => ({
    user: { full_name: "Ada Lovelace", email: "ada@example.com" },
  }),
  useAgents: () => ({ agents: env.agents, isLoading: env.loading }),
}));
// Kept per organization, read from their own route (Codex on #2324), and read
// only for the starter agent: `asked` counts who mounted the query.
const asked = vi.hoisted(() => ({ count: 0 }));
vi.mock("@/hooks/use-suggestions", () => ({
  usePersonalStarterQuery: (enabled: boolean) => {
    if (enabled) asked.count += 1;
    return { data: env.personal ?? [], isPending: env.personalLoading };
  },
}));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (state: { selectedAgentId: string }) => unknown) =>
    select({ selectedAgentId: "a1" }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

const AGENT = { id: "a1", slug: "amigo", name: "Amigo", has_avatar: false, avatar_color: 0 };

describe("ChatEmptyState", () => {
  it("keeps inbox, background previews and keyboard hints off the welcome screen", () => {
    render(<ChatEmptyState onPick={vi.fn()} />);
    expect(screen.queryByText("Needs your attention")).toBeNull();
    expect(screen.queryByText("Background work")).toBeNull();
    expect(screen.queryByText("command palette")).toBeNull();
    expect(screen.queryByText("slash commands")).toBeNull();
  });

  it.each([
    [0, "greetingNight"],
    [5, "greetingNight"],
    [6, "greetingMorning"],
    [11, "greetingMorning"],
    [12, "greetingAfternoon"],
    [17, "greetingAfternoon"],
    [18, "greetingEvening"],
    [23, "greetingEvening"],
  ] as const)("greets the reader for local hour %i", (hour, key) => {
    expect(greetingKey(hour)).toBe(key);
  });

  it("does not paint default prompts before the selected agent arrives", () => {
    env.loading = true;
    env.agents = [];
    const view = render(<ChatEmptyState onPick={vi.fn()} />);
    expect(screen.queryByText("Set up a routine")).toBeNull();
    expect(view.container.querySelector('[aria-busy="true"]')).not.toBeNull();
    env.loading = false;
    env.agents = [{ ...AGENT, starters: ["My published starter"] }];
    view.rerender(<ChatEmptyState onPick={vi.fn()} />);
    expect(screen.getByText("My published starter")).toBeInTheDocument();
    expect(screen.queryByText("Set up a routine")).toBeNull();
  });

  it("waits for personal prompts without replacing temporary defaults", () => {
    env.agents = [{ ...AGENT, slug: "agenticos", starters: [] }];
    env.personalLoading = true;
    const view = render(<ChatEmptyState onPick={vi.fn()} />);
    expect(screen.queryByText("Set up a routine")).toBeNull();
    env.personalLoading = false;
    env.personal = ["My personal starter"];
    view.rerender(<ChatEmptyState onPick={vi.fn()} />);
    expect(screen.getByText("My personal starter")).toBeInTheDocument();
  });

  beforeEach(() => {
    env.agents = [{ ...AGENT, starters: [] }];
    env.personal = null;
    env.loading = false;
    env.personalLoading = false;
    asked.count = 0;
  });

  it("opens the starter agent's chat on the person's own first messages", async () => {
    env.agents = [{ ...AGENT, slug: "agenticos", name: "AgenticOS", starters: [] }];
    env.personal = ["Show my pipeline", "Plan my Monday"];
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: "Show my pipeline" }));

    expect(onPick).toHaveBeenCalledWith("Show my pipeline");
    expect(screen.queryByText("Set up a routine")).toBeNull();
  });

  it("renders the published opener icon without changing the message it sends", async () => {
    env.agents = [
      {
        ...AGENT,
        starters: ["Draft my email"],
        starter_icons: { "Draft my email": "mail" },
        starter_titles: { "Draft my email": "Write email" },
      },
    ];
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);
    const card = screen.getByRole("button", { name: /Write email\s*Draft my email/ });
    expect(screen.getByText("Write email")).toBeInTheDocument();
    expect(screen.getByText("Draft my email")).toBeInTheDocument();
    expect(card.querySelector(".lucide-mail")).not.toBeNull();
    await userEvent.click(card);
    expect(onPick).toHaveBeenCalledWith("Draft my email");
  });

  it("keeps personal first messages to the starter agent", () => {
    env.personal = ["Show my pipeline"];
    render(<ChatEmptyState onPick={vi.fn()} />);

    expect(screen.queryByText("Show my pipeline")).toBeNull();
    // Personalized openers are still fetched only for the starter agent.
    expect(asked.count).toBe(0);
  });

  it.each(["architect", "coder", "custom-assistant"])("shows %s's own first messages", (slug) => {
    env.agents = [{ ...AGENT, slug, starters: ["My own opener"] }];
    render(<ChatEmptyState onPick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "My own opener" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Ada/ })).toBeInTheDocument();
    expect(asked.count).toBe(0);
  });

  it("offers the chat's own to the starter agent before its first night", () => {
    env.agents = [{ ...AGENT, slug: "agenticos", starters: [] }];
    render(<ChatEmptyState onPick={vi.fn()} />);

    expect(screen.getByText("Set up a routine")).toBeInTheDocument();
  });

  it("offers the agent's own first messages, which send as written (#2301)", async () => {
    // Even for an agent that draws: what its author wrote comes first.
    env.agents = [{ ...AGENT, starters: ["How do refunds work?", "Where is my order?"] }];
    env.agents = env.agents.map((agent) => ({ ...agent, published_capabilities: ["visuals"] }));
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: "How do refunds work?" }));

    expect(onPick).toHaveBeenCalledWith("How do refunds work?");
    expect(screen.queryByText("Set up a routine")).toBeNull();
    expect(screen.queryByText("Plan a trip on a map")).toBeNull();
  });

  it("offers the chat's own for an agent with none, among them what it can do", async () => {
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: /What can you do\?/ }));

    expect(onPick).toHaveBeenCalledWith(expect.stringContaining("What can you do for me here?"));
    expect(screen.getByText("Set up a routine")).toBeInTheDocument();
    expect(screen.getByText("Summarize my docs")).toBeInTheDocument();
    expect(screen.queryByText("Plan a trip on a map")).toBeNull();
  });

  it("opens on one starter per kind of interactive answer for an agent that draws", async () => {
    env.agents = env.agents.map((agent) => ({ ...agent, published_capabilities: ["visuals"] }));
    const onPick = vi.fn();
    render(<ChatEmptyState onPick={onPick} />);

    for (const title of [
      "Explain it in 3D",
      "Compare, then chart it",
      "Make a calculator",
      "Plan a trip on a map",
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    expect(screen.queryByText("Summarize my docs")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /^Plan a trip on a map/ }));
    expect(onPick).toHaveBeenCalledWith(expect.stringContaining("on a map"));
  });
});

it("renders stable server markup without guessing a local-time greeting", () => {
  const html = renderToString(<ChatEmptyState onPick={vi.fn()} />);
  expect(html).not.toContain("Good morning");
});

it("shows a neutral avatar skeleton rather than a demo mark while resolving the agent", () => {
  env.loading = true;
  env.agents = [];
  render(<ChatEmptyState onPick={vi.fn()} />);
  expect(screen.getByTestId("welcome-agent-loading")).toBeVisible();
});
