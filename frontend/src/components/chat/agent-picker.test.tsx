import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentPicker } from "./agent-picker";
import type { Agent, AgentStatus } from "@/types/agents";

const listed = vi.fn<() => Agent[]>(() => []);
const selectedId = vi.fn<() => string | null>(() => null);
const select = vi.fn();

vi.mock("@/hooks", () => ({
  useAgents: () => ({ agents: listed(), isLoading: loading }),
}));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (pick: (state: unknown) => unknown) =>
    pick({ selectedAgentId: selectedId(), select }),
  useConversationStore: (pick: (state: unknown) => unknown) =>
    pick({ currentConversationId: "c1" }),
}));

let loading = false;

const agent = (
  id: string,
  name: string,
  status: AgentStatus = "published",
  description: string | null = null,
): Agent => ({
  id,
  slug: name.toLowerCase(),
  name,
  description,
  status,
  visibility: "private",
  owner_user_id: null,
  current_version_id: status === "published" ? "v1" : null,
});

const PUBLISHED: Agent[] = [
  agent("a1", "Support", "published", "Answers customer questions."),
  agent("a2", "Sales"),
];

/** Opens the popover; every assertion below is about what is inside it. */
async function open(agents: Agent[] = PUBLISHED, selected: string | null = null) {
  listed.mockReturnValue(agents);
  selectedId.mockReturnValue(selected);
  render(<AgentPicker />);
  await userEvent.click(screen.getByRole("button", { name: /^Agent:/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  loading = false;
});

describe("the chat's agent picker", () => {
  it("names the agent on the trigger, so it is readable without opening", async () => {
    // It was a tab inside a settings popover: the most consequential choice in
    // the conversation, two clicks away and invisible until you got there.
    listed.mockReturnValue(PUBLISHED);
    selectedId.mockReturnValue("a1");

    render(<AgentPicker />);

    expect(screen.getByRole("button", { name: "Agent: Support" })).toBeInTheDocument();
  });

  it("shows the agent's face on the trigger", async () => {
    // Radix only swaps in the <img> once the image has loaded, which jsdom
    // never does - so what is assertable here is that the avatar mounted for
    // this agent, by the initials it falls back to.
    listed.mockReturnValue([{ ...PUBLISHED[0]!, has_avatar: true }]);
    selectedId.mockReturnValue("a1");

    render(<AgentPicker />);

    const trigger = screen.getByRole("button", { name: "Agent: Support" });
    expect(within(trigger).getByText("S")).toBeInTheDocument();
  });

  it("offers the general assistant as a listed choice, first", async () => {
    // Not an empty state: "nothing selected" reads as a broken picker, and the
    // assistant is a real product rather than the absence of an agent.
    await open();

    const options = screen.getAllByRole("radio");
    expect(options[0]).toHaveAccessibleName(/General assistant/);
    expect(options[0]).toHaveAttribute("aria-checked", "true");
  });

  it("lists the published agents alongside it", async () => {
    await open();

    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByText("Support")).toBeInTheDocument();
    expect(screen.getByText("Sales")).toBeInTheDocument();
  });

  it("marks the selected agent and only that one", async () => {
    await open(PUBLISHED, "a2");

    const [assistant, support, sales] = screen.getAllByRole("radio");
    expect(assistant).toHaveAttribute("aria-checked", "false");
    expect(support).toHaveAttribute("aria-checked", "false");
    expect(sales).toHaveAttribute("aria-checked", "true");
  });

  it("reports the agent that was picked", async () => {
    await open();

    await userEvent.click(screen.getByText("Support"));

    expect(select).toHaveBeenCalledWith("a1");
  });

  it("reports null when the general assistant is picked back", async () => {
    // The way back matters as much as the way in - an agent chat has a budget
    // and a run history the assistant does not, and users need to leave it.
    await open(PUBLISHED, "a1");

    await userEvent.click(screen.getByText("General assistant"));

    expect(select).toHaveBeenCalledWith(null);
  });

  it("says a switch applies from the next message, not retroactively", async () => {
    // Changing agent mid-conversation is supported; what it cannot do is
    // reattribute the answers already above it.
    await open();

    expect(screen.getByText(/Applies from your next message/)).toBeInTheDocument();
  });

  it("offers neither a draft nor an archived agent", async () => {
    // Neither has a published version, so the backend refuses to run one.
    // Listing it here would turn the picker into a trap.
    await open([
      agent("d1", "Half-built", "draft"),
      agent("r1", "Retired", "archived"),
      ...PUBLISHED,
    ]);

    expect(screen.queryByText("Half-built")).not.toBeInTheDocument();
    expect(screen.queryByText("Retired")).not.toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("still offers the assistant when nothing has been published", async () => {
    await open([]);

    expect(screen.getAllByRole("radio")).toHaveLength(1);
    expect(screen.getByText(/No published agents yet/)).toBeInTheDocument();
  });

  it("does not claim there is nothing published while the list is still loading", async () => {
    loading = true;

    await open([]);

    expect(screen.queryByText(/No published agents yet/)).not.toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
