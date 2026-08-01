import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentPicker } from "./agent-picker";
import type { Agent, AgentStatus } from "@/types/agents";

const listed = vi.fn<() => Agent[]>(() => []);
const selectedId = vi.fn<() => string | null>(() => null);
const defaultId = vi.fn<() => string | null>(() => null);
const select = vi.fn();
const setDefault = vi.fn();

vi.mock("@/hooks", () => ({
  useAgents: () => ({ agents: listed(), isLoading: loading, isFetching: loading || fetching }),
}));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (pick: (state: unknown) => unknown) =>
    pick({ selectedAgentId: selectedId(), defaultAgentId: defaultId(), select, setDefault }),
  useConversationStore: (pick: (state: unknown) => unknown) =>
    pick({ currentConversationId: "c1" }),
}));

let loading = false;
/** A refetch in flight over data already on screen - the stale-while-revalidate window. */
let fetching = false;

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
async function open(agents: Agent[] = PUBLISHED, selected: string | null = "a1") {
  listed.mockReturnValue(agents);
  selectedId.mockReturnValue(selected);
  render(<AgentPicker />);
  await userEvent.click(screen.getByRole("button", { name: /^Agent:/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  // clearAllMocks does not undo mockReturnValue - reset the default star
  // explicitly so one test's default does not leak into the next.
  defaultId.mockReturnValue(null);
  loading = false;
  fetching = false;
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

  it("does not offer a general assistant - only the published agents", async () => {
    // The chat runs the organization's agents, and nothing else. A row for
    // "no agent" would be an offer the backend cannot honestly serve.
    await open();

    expect(screen.queryByText(/General assistant/)).not.toBeInTheDocument();
    const options = screen.getAllByRole("radio");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveAccessibleName(/Support/);
    expect(options[1]).toHaveAccessibleName(/Sales/);
  });

  it("resolves an empty selection to the first published agent", async () => {
    // The store starts at null (or points at an agent that was unpublished);
    // the composer must never send into a void, so the picker claims the
    // first published agent as soon as the list arrives.
    listed.mockReturnValue(PUBLISHED);
    selectedId.mockReturnValue(null);

    render(<AgentPicker />);

    expect(select).toHaveBeenCalledWith("a1");
  });

  it("resolves an empty selection to the starred default, not the first agent", async () => {
    // The default exists precisely so a fresh browser or a new chat does not
    // land on whoever happens to be first in the list.
    listed.mockReturnValue(PUBLISHED);
    selectedId.mockReturnValue(null);
    defaultId.mockReturnValue("a2");

    render(<AgentPicker />);

    expect(select).toHaveBeenCalledWith("a2");
  });

  it("ignores a starred default that is no longer published", async () => {
    // An unpublished default cannot answer; falling back to the first
    // published agent keeps the composer addressed to someone real.
    listed.mockReturnValue([agent("d1", "Half-built", "draft"), ...PUBLISHED]);
    selectedId.mockReturnValue(null);
    defaultId.mockReturnValue("d1");

    render(<AgentPicker />);

    expect(select).toHaveBeenCalledWith("a1");
  });

  it("stars an agent as default without selecting it", async () => {
    await open(PUBLISHED, "a1");

    await userEvent.click(screen.getByRole("button", { name: "Set Sales as default agent" }));

    expect(setDefault).toHaveBeenCalledWith("a2");
    expect(select).not.toHaveBeenCalled();
  });

  it("unstars the current default", async () => {
    defaultId.mockReturnValue("a2");
    await open(PUBLISHED, "a1");

    await userEvent.click(screen.getByRole("button", { name: "Unset Sales as default agent" }));

    expect(setDefault).toHaveBeenCalledWith(null);
  });

  it("labels the default agent in the list", async () => {
    defaultId.mockReturnValue("a2");
    await open(PUBLISHED, "a1");

    expect(screen.getByText("Default")).toBeInTheDocument();
  });

  it("does not auto-select while the list is still loading", async () => {
    // An empty list mid-flight is not "nothing published" - claiming an agent
    // from it would overwrite a valid stored selection with nothing.
    loading = true;
    listed.mockReturnValue([]);
    selectedId.mockReturnValue(null);

    render(<AgentPicker />);

    expect(select).not.toHaveBeenCalled();
  });

  it("does not replace a selection the list has not caught up with", async () => {
    // The Builder's "Open in chat" selects an agent and navigates. If that agent
    // was published a moment ago, the list this render sees is the previous one
    // being revalidated - so the id resolves to nothing, and falling back here
    // would hand the conversation to a different agent than the one asked for.
    fetching = true;
    listed.mockReturnValue(PUBLISHED);
    selectedId.mockReturnValue("a9-just-published");

    render(<AgentPicker />);

    expect(select).not.toHaveBeenCalled();
  });

  it("still fills in an empty choice while the list is being revalidated", async () => {
    // The guard above is about *replacing* a choice. Having made none is the
    // ordinary first visit, and leaving the composer addressed to nobody
    // through every background refetch is not a fix for anything.
    fetching = true;
    listed.mockReturnValue(PUBLISHED);
    selectedId.mockReturnValue(null);

    render(<AgentPicker />);

    expect(select).toHaveBeenCalledWith("a1");
  });

  it("marks the selected agent and only that one", async () => {
    await open(PUBLISHED, "a2");

    const [support, sales] = screen.getAllByRole("radio");
    expect(support).toHaveAttribute("aria-checked", "false");
    expect(sales).toHaveAttribute("aria-checked", "true");
  });

  it("reports the agent that was picked", async () => {
    await open(PUBLISHED, "a2");

    await userEvent.click(screen.getByText("Support"));

    expect(select).toHaveBeenCalledWith("a1");
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
    expect(screen.getAllByRole("radio")).toHaveLength(2);
  });

  it("offers nothing when nothing has been published", async () => {
    await open([], null);

    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.getByText(/No published agents yet/)).toBeInTheDocument();
  });

  it("does not claim there is nothing published while the list is still loading", async () => {
    loading = true;

    await open([], null);

    expect(screen.queryByText(/No published agents yet/)).not.toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
