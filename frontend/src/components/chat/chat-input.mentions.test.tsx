import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Mentionable } from "@/types/mention";
import { ChatInput } from "./chat-input";

const DRIVE: Mentionable = { kind: "mcp", id: "gdrive", name: "Google Drive", detail: "gdrive_*" };
const REVIEWER: Mentionable = {
  kind: "agent",
  id: "a-review",
  name: "Reviewer",
  slug: "reviewer",
  delegate: true,
};
const WRITER: Mentionable = { kind: "agent", id: "a-writer", name: "Writer", slug: "writer" };
const CONTRACTS: Mentionable = { kind: "collection", id: "kb-1", name: "Contracts" };

const offered = vi.fn(() => ({ items: [DRIVE, REVIEWER, WRITER, CONTRACTS], isLoading: false }));
vi.mock("@/hooks/use-mentionables", () => ({
  useMentionables: (agentId: string | null, enabled: boolean) => {
    expect(typeof enabled).toBe("boolean");
    return agentId === null ? { items: [], isLoading: false } : offered();
  },
}));
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

function composer(props: Partial<React.ComponentProps<typeof ChatInput>> = {}) {
  const onSend = vi.fn();
  const onAgentMentioned = vi.fn();
  const view = render(
    <ChatInput onSend={onSend} agentId="a-chat" onAgentMentioned={onAgentMentioned} {...props} />,
  );
  const box = screen.getByRole("textbox") as HTMLTextAreaElement;
  return { onSend, onAgentMentioned, box, view };
}

beforeEach(() => {
  vi.clearAllMocks();
  offered.mockReturnValue({ items: [DRIVE, REVIEWER, WRITER, CONTRACTS], isLoading: false });
});

describe("@-mentions in the composer", () => {
  it("offers what matches as the person types, grouped, and picks one into a chip", async () => {
    const { box, onSend } = composer();
    await userEvent.type(box, "find the brief in @goo");

    const menu = screen.getByRole("listbox", { name: "Point the agent at" });
    expect(menu).toHaveTextContent("MCP servers");
    const [only, ...others] = screen.getAllByRole("option");
    expect(others).toEqual([]);
    expect(only).toHaveTextContent("Google Drivegdrive_*");

    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(box.value).toBe("find the brief in ");
    expect(screen.getByTitle("gdrive_*")).toHaveTextContent("Google Drive");

    await userEvent.type(box, "now{Enter}");
    expect(onSend).toHaveBeenCalledWith("find the brief in now", undefined, undefined, [DRIVE]);
    expect(screen.queryByTitle("gdrive_*")).toBeNull();
  });

  it("moves through the menu with the arrows and Tab, and closes on Escape", async () => {
    const { box } = composer();
    await userEvent.type(box, "@");
    expect(screen.getAllByRole("option")).toHaveLength(4);

    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{ArrowUp}{ArrowUp}");
    expect(screen.getAllByRole("option")[3]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Tab}");
    expect(screen.getByTitle("Contracts")).toBeInTheDocument();

    await userEvent.type(box, "@");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(box.value).toBe("@");
  });

  it("does not offer what is already picked, and a chip can be taken back", async () => {
    const { box } = composer();
    await userEvent.type(box, "@con");
    await userEvent.click(screen.getByRole("option", { name: /Contracts/ }));
    await userEvent.type(box, "@con");
    expect(screen.getByRole("listbox")).toHaveTextContent("Nothing this agent can use matches.");

    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Remove Contracts" }));
    expect(screen.queryByTitle("Contracts")).toBeNull();
  });

  it("hands a delegate the work, and lets an agent it cannot delegate to answer instead", async () => {
    const { box, onAgentMentioned } = composer();
    await userEvent.type(box, "@rev");
    expect(screen.getByRole("option", { name: /Reviewer/ })).toHaveTextContent("hands work to it");
    await userEvent.keyboard("{Enter}");
    expect(screen.getByTitle("Reviewer")).toBeInTheDocument();

    await userEvent.type(box, "@wri");
    expect(screen.getByRole("option", { name: /Writer/ })).toHaveTextContent("answers instead");
    await userEvent.keyboard("{Enter}");
    expect(onAgentMentioned).toHaveBeenCalledWith("a-writer");
    expect(screen.queryByTitle("Writer")).toBeNull();
  });

  it("drops what was picked for one agent when the thread switches to another", async () => {
    const { box, view } = composer();
    await userEvent.type(box, "@goo{Enter}");
    expect(screen.getByTitle("gdrive_*")).toBeInTheDocument();

    view.rerender(<ChatInput onSend={vi.fn()} agentId="a-other" />);
    expect(screen.queryByTitle("gdrive_*")).toBeNull();
  });

  it("is not an email address, and offers nothing where the composer has no agent", async () => {
    const { box, view } = composer();
    await userEvent.type(box, "mail ann@exa");
    expect(screen.queryByRole("listbox")).toBeNull();

    view.unmount();
    const quiet = composer({ agentId: null });
    await userEvent.type(quiet.box, "@goo");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("says it is loading before the agent's list arrives, and picks with the mouse", async () => {
    offered.mockReturnValue({ items: [], isLoading: true });
    const { box } = composer();
    fireEvent.change(box, { target: { value: "@", selectionStart: 1 } });
    expect(screen.getByRole("listbox")).toHaveTextContent("Loading what this agent can use");

    offered.mockReturnValue({ items: [DRIVE], isLoading: false });
    fireEvent.change(box, { target: { value: "@dr", selectionStart: 3 } });
    fireEvent.mouseEnter(screen.getByRole("option", { name: /Google Drive/ }));
    fireEvent.mouseDown(screen.getByRole("option", { name: /Google Drive/ }));
    expect(screen.getByTitle("gdrive_*")).toBeInTheDocument();
  });
});
