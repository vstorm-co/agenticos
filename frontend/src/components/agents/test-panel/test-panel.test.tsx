import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TestPanel } from "./test-panel";
import { ASK, NEW, REPLAY } from "@/lib/assistant-messages";
import { readTestPanel, TEST_PANEL_OPEN, writeTestPanel } from "@/lib/test-panel-state";
import type { AgentEnvironment } from "@/types/agents";

const PRODUCTION = {
  id: "env-prod",
  agent_id: "a1",
  name: "production",
  version_id: "v3",
  version: 3,
  is_default: true,
} as AgentEnvironment;

function open(props: Partial<Parameters<typeof TestPanel>[0]> = {}) {
  const onClose = vi.fn();
  render(
    <TestPanel
      agentId="a1"
      published
      environments={[PRODUCTION]}
      saving={false}
      onClose={onClose}
      {...props}
    />,
  );
  const frame = screen.getByTitle("Test") as HTMLIFrameElement;
  const post = vi.fn();
  Object.defineProperty(frame, "contentWindow", { value: { postMessage: post } });
  return { onClose, frame, post };
}

beforeEach(() => window.localStorage.clear());

describe("the Builder's test panel", () => {
  it("tries the draft by default, saying nothing is published", () => {
    const { frame } = open();

    expect(frame.getAttribute("src")).toBe("/agent-test-frame?agent=a1&mode=draft");
    expect(screen.getByRole("status")).toHaveTextContent("Nothing is published");
  });

  it("says when the latest change is still being saved", () => {
    open({ saving: true });

    expect(screen.getByRole("status")).toHaveTextContent("Saving your latest change");
  });

  it("answers with an environment's version once it is chosen, and remembers it", async () => {
    open();

    await userEvent.click(screen.getByRole("combobox", { name: "What answers" }));
    await userEvent.click(await screen.findByRole("option", { name: "production (version 3)" }));

    expect((screen.getByTitle("Test") as HTMLIFrameElement).getAttribute("src")).toContain(
      "mode=env-prod",
    );
    expect(screen.getByRole("status")).toHaveTextContent("production, version 3");
    expect(readTestPanel("a1").mode).toBe("env-prod");
  });

  it("falls back to the draft when the agent has nothing published, or the environment is gone", () => {
    writeTestPanel("a1", { open: true, width: 440, mode: "env-prod", pinned: [] });
    const { frame } = open({ published: false });
    expect(frame.getAttribute("src")).toContain("mode=draft");
  });

  it("starts over, replays and runs a pinned prompt in the frame", async () => {
    const { post } = open();

    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    await userEvent.click(screen.getByRole("button", { name: "Send the last message again" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Pin a test prompt" }), "Refunds?");
    await userEvent.click(screen.getByRole("button", { name: "Pin a test prompt" }));
    await userEvent.click(screen.getByRole("button", { name: "Refunds?" }));

    expect(post.mock.calls.map((call) => call[0])).toEqual([
      { type: NEW },
      { type: REPLAY },
      { type: ASK, text: "Refunds?" },
    ]);
    expect(readTestPanel("a1").pinned).toEqual(["Refunds?"]);
  });

  it("pins a prompt once, and unpins it", async () => {
    open();
    const input = screen.getByRole("textbox", { name: "Pin a test prompt" });

    await userEvent.type(input, "Refunds?{Enter}");
    await userEvent.type(input, "Refunds?{Enter}");
    expect(screen.getAllByRole("button", { name: "Refunds?" })).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Unpin Refunds?" }));
    expect(screen.queryByRole("button", { name: "Refunds?" })).toBeNull();
  });

  it("is resized from its edge, within bounds, and keeps the width", () => {
    open();
    const edge = screen.getByRole("separator", { name: "Resize the test panel" });

    fireEvent.pointerDown(edge, { clientX: 1000 });
    fireEvent.pointerMove(window, { clientX: 700 });
    fireEvent.pointerUp(window);

    expect(readTestPanel("a1").width).toBe(740);

    fireEvent.pointerDown(edge, { clientX: 1000 });
    fireEvent.pointerMove(window, { clientX: 5000 });
    fireEvent.pointerUp(window);
    expect(readTestPanel("a1").width).toBe(320);
  });

  it("closes", async () => {
    const { onClose } = open();

    await userEvent.click(screen.getByRole("button", { name: "Close the test panel" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("asks the Architect's corner widget to step aside while it is open", () => {
    open();
    expect(document.documentElement.hasAttribute(TEST_PANEL_OPEN)).toBe(true);

    cleanup();

    expect(document.documentElement.hasAttribute(TEST_PANEL_OPEN)).toBe(false);
  });
});
