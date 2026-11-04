import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillShortcut } from "./skill-shortcut";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import { Perm, type Permission } from "@/types/permissions";

/**
 * "Make a skill of this" (#2301): the Architect, which cannot see the chat, is
 * handed what was asked and how it was answered - and only somebody who may
 * write skills is offered it.
 */

const state = vi.hoisted(() => ({
  held: [] as string[],
  assistant: null as { status: string; can_use: boolean } | null,
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => state.held.includes(permission) }),
}));
vi.mock("@/hooks/use-assistant", () => ({ useAssistant: () => ({ assistant: state.assistant }) }));

const REQUEST = "Compare these three vendors";
const ANSWER = "I read each pricing page, then built a table.";

beforeEach(() => {
  state.held = [Perm.skillsEdit];
  state.assistant = { status: "ready", can_use: true };
  useArchitectAskStore.setState({ request: null });
});

describe("SkillShortcut", () => {
  it("hands the Architect the request and the answer", async () => {
    render(<SkillShortcut request={REQUEST} answer={ANSWER} />);

    await userEvent.click(screen.getByRole("button", { name: "Make a skill of this" }));

    const text = useArchitectAskStore.getState().request?.text;
    expect(text).toContain(REQUEST);
    expect(text).toContain(ANSWER);
  });

  it("hands a saved turn's conversation over to be read whole", async () => {
    // The steps and tool calls that made the answer are in the conversation, not
    // in its last words.
    render(<SkillShortcut request={REQUEST} answer={ANSWER} conversationId="c-42" />);

    await userEvent.click(screen.getByRole("button", { name: "Make a skill of this" }));

    const text = useArchitectAskStore.getState().request?.text;
    expect(text).toContain("c-42");
    expect(text).toContain("read_conversation");
    expect(text).toContain(REQUEST);
    expect(text).not.toContain(ANSWER);
  });

  it("cuts a long answer short rather than flooding the Architect", async () => {
    render(<SkillShortcut request={REQUEST} answer={`${"a".repeat(2000)}TAIL`} />);

    await userEvent.click(screen.getByRole("button", { name: "Make a skill of this" }));

    expect(useArchitectAskStore.getState().request?.text).not.toContain("TAIL");
  });

  it("is not offered to somebody who may not write skills", () => {
    state.held = [Perm.agentsRun];
    render(<SkillShortcut request={REQUEST} answer={ANSWER} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([
    ["the Architect is switched off for them", { status: "ready", can_use: false }],
    ["the Architect is not ready", { status: "loading", can_use: true }],
    ["there is no Architect", null],
  ])("is not offered when %s", (_, assistant) => {
    state.assistant = assistant;
    render(<SkillShortcut request={REQUEST} answer={ANSWER} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
