import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Mentionable } from "@/types/mention";
import { ChatInput } from "./chat-input";
import { messageOf } from "./composer-editor";

const DRIVE: Mentionable = { kind: "mcp", id: "gdrive", name: "Google Drive", detail: "gdrive_*" };
const REVIEWER: Mentionable = { kind: "agent", id: "a-review", name: "Reviewer", slug: "reviewer" };
const SEARCH: Mentionable = {
  kind: "capability",
  id: "web_research",
  name: "Web research",
  icon: "web_search",
};
const CONTRACTS: Mentionable = { kind: "collection", id: "kb-1", name: "Contracts" };

const offered = vi.fn(() => ({
  items: [DRIVE, SEARCH, REVIEWER, CONTRACTS],
  isLoading: false,
  isError: false,
}));
vi.mock("@/hooks/use-mentionables", () => ({
  useMentionables: (agentId: string | null) =>
    agentId === null ? { items: [], isLoading: false, isError: false } : offered(),
}));
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

function composer(props: Partial<React.ComponentProps<typeof ChatInput>> = {}) {
  const onSend = vi.fn();
  const view = render(<ChatInput onSend={onSend} agentId="a-chat" {...props} />);
  const box = screen.getByRole("textbox");
  /** What the message names as chips. */
  const marked = () =>
    [...box.querySelectorAll<HTMLElement>('[data-chip="mention"]')].map(
      (chip) => chip.dataset.text,
    );
  return { onSend, box, view, marked };
}

/** Replace what the box holds, the caret at its end - an edit the keyboard would take longer to make. */
function setText(box: HTMLElement, text: string) {
  box.textContent = text;
  const range = document.createRange();
  range.selectNodeContents(box);
  range.collapse(false);
  window.getSelection()!.removeAllRanges();
  window.getSelection()!.addRange(range);
  fireEvent.input(box);
}

beforeEach(() => {
  vi.clearAllMocks();
  offered.mockReturnValue({
    items: [DRIVE, SEARCH, REVIEWER, CONTRACTS],
    isLoading: false,
    isError: false,
  });
});

describe("@-mentions in the composer", () => {
  it("offers what matches as the person types, and makes the pick a chip in the text", async () => {
    const { box, onSend, marked } = composer();
    await userEvent.type(box, "find the brief in @goo");

    const menu = screen.getByRole("listbox", { name: "Point the agent at" });
    expect(menu).toHaveTextContent("MCP servers");
    const [only, ...others] = screen.getAllByRole("option");
    expect(others).toEqual([]);
    expect(only).toHaveTextContent("Google Drivegdrive_*");

    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(messageOf(box)).toBe("find the brief in @Google Drive ");
    expect(marked()).toEqual(["@Google Drive"]);
    // A chip is one thing: the caret steps over it and nobody edits half a name.
    const chip = box.querySelector('[data-chip="mention"]')!;
    expect(chip).toHaveAttribute("contenteditable", "false");
    expect(chip).toHaveTextContent("Google Drive");

    await userEvent.type(box, "now{Enter}");
    expect(onSend).toHaveBeenCalledWith(
      "find the brief in @Google Drive now",
      undefined,
      undefined,
      [DRIVE],
    );
    expect(marked()).toEqual([]);
    expect(messageOf(box)).toBe("");
  });

  it("moves through the menu with the arrows and Tab, and closes on Escape", async () => {
    const { box, marked } = composer();
    await userEvent.type(box, "@");
    expect(screen.getAllByRole("option")).toHaveLength(4);

    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{ArrowUp}{ArrowUp}");
    expect(screen.getAllByRole("option")[3]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Tab}");
    expect(marked()).toEqual(["@Contracts"]);

    await userEvent.type(box, "@");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(messageOf(box)).toBe("@Contracts @");
  });

  it("stops at the ten the server takes, and says so", async () => {
    const many: Mentionable[] = Array.from({ length: 11 }, (_, n) => ({
      kind: "collection",
      id: `kb-${n}`,
      name: `Book${n}`,
    }));
    offered.mockReturnValue({ items: many, isLoading: false, isError: false });
    const { box, marked } = composer();
    for (let n = 0; n < 10; n += 1) {
      await userEvent.type(box, `@Book${n}`);
      await userEvent.click(screen.getByRole("option", { name: new RegExp(`^Book${n}$`) }));
    }
    expect(marked()).toHaveLength(10);

    await userEvent.type(box, "@Book10");
    expect(screen.getByText("You can point at 10 things at most in one message.")).toBeVisible();
    expect(screen.queryByRole("option")).toBeNull();
  });

  it("keeps offering what is already picked, and a deleted chip is unpicked", async () => {
    const { box, onSend, marked } = composer();
    await userEvent.type(box, "@con");
    await userEvent.click(screen.getByRole("option", { name: /Contracts/ }));
    await userEvent.type(box, "and @con");
    await userEvent.click(screen.getByRole("option", { name: /Contracts/ }));
    expect(marked()).toEqual(["@Contracts", "@Contracts"]);
    await userEvent.type(box, "{Enter}");
    // Named twice, sent once.
    expect(onSend).toHaveBeenLastCalledWith("@Contracts and @Contracts", undefined, undefined, [
      CONTRACTS,
    ]);

    setText(box, "@Contrac ");
    expect(marked()).toEqual([]);
    await userEvent.type(box, "{Enter}");
    expect(onSend).toHaveBeenLastCalledWith("@Contrac", undefined, undefined, undefined);
  });

  it("tells the agent who to hand the work to, without changing who answers", async () => {
    const { box, onSend, marked } = composer();
    await userEvent.type(box, "@rev");
    await userEvent.keyboard("{Enter}");
    expect(marked()).toEqual(["@Reviewer"]);
    await userEvent.type(box, "check it{Enter}");
    expect(onSend).toHaveBeenCalledWith("@Reviewer check it", undefined, undefined, [REVIEWER]);
  });

  it("offers a capability by the name people know it by, however it is typed", async () => {
    const { box, marked } = composer();
    await userEvent.type(box, "@webresea");
    expect(screen.getByRole("listbox")).toHaveTextContent("Capabilities");
    await userEvent.keyboard("{Enter}");
    expect(marked()).toEqual(["@Web research"]);
  });

  it("drops what was picked for one agent when the thread switches to another", async () => {
    const { box, view, marked } = composer();
    await userEvent.type(box, "@goo{Enter}");
    expect(marked()).toEqual(["@Google Drive"]);

    view.rerender(<ChatInput onSend={vi.fn()} agentId="a-other" />);
    expect(marked()).toEqual([]);
    // The words stay; only the chip is gone, since the other agent cannot reach it.
    expect(messageOf(box)).toBe("@Google Drive ");
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

  it("says it is loading, says when the list failed, and picks with the mouse", async () => {
    offered.mockReturnValue({ items: [], isLoading: true, isError: false });
    const { box, marked } = composer();
    setText(box, "@");
    expect(screen.getByRole("listbox")).toHaveTextContent("Loading what this agent can use");

    offered.mockReturnValue({ items: [], isLoading: false, isError: true });
    setText(box, "@d");
    expect(screen.getByRole("listbox")).toHaveTextContent(
      "Could not load what this agent can use.",
    );

    offered.mockReturnValue({ items: [DRIVE], isLoading: false, isError: false });
    setText(box, "@dr");
    fireEvent.mouseEnter(screen.getByRole("option", { name: /Google Drive/ }));
    fireEvent.mouseDown(screen.getByRole("option", { name: /Google Drive/ }));
    expect(marked()).toEqual(["@Google Drive"]);
  });
});

describe("a project from @", () => {
  const LAUNCH: Mentionable = { kind: "project", id: "p-1", name: "Launch", detail: "Q4" };

  it("starts the chat in it rather than writing it into the message", async () => {
    const onPickProject = vi.fn();
    const { box, onSend, marked } = composer({ projects: [LAUNCH], onPickProject });
    await userEvent.type(box, "plan @laun");

    expect(screen.getByRole("listbox")).toHaveTextContent("Projects");
    await userEvent.keyboard("{Enter}");

    expect(onPickProject).toHaveBeenCalledWith("p-1");
    expect(messageOf(box)).toBe("plan ");
    expect(marked()).toEqual([]);

    await userEvent.type(box, "it{Enter}");
    expect(onSend).toHaveBeenCalledWith("plan it", undefined, undefined, undefined);
  });

  it("is not offered where the chat cannot choose a project", async () => {
    const { box } = composer();
    await userEvent.type(box, "@laun");
    expect(screen.queryByRole("option")).toBeNull();
  });
});
