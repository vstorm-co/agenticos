import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NODE_DRAG_MIME } from "@/components/workflows/palette";
import { makeDefinition } from "@/components/workflows/validation/fixtures";

import { NodePicker } from "./node-picker";

const SEND = makeDefinition({
  id: "slack.message.send",
  category: "slack",
  name: "Send a message",
  description: "Post to Slack",
});
const READ = makeDefinition({
  id: "slack.messages.read",
  category: "slack",
  name: "Read messages",
  description: "Read Slack",
});
const AGENT = makeDefinition({
  id: "agent.run",
  category: "agent",
  name: "Run an agent",
  description: "Ask an agent",
});
const OFFERED = [READ, SEND, AGENT];

function mount(draggable = false) {
  const onPick = vi.fn();
  render(<NodePicker offered={OFFERED} onPick={onPick} draggable={draggable} />);
  return onPick;
}

describe("NodePicker", () => {
  it("lists sections of groups, a lone step at once, and a group's steps one level down", async () => {
    const onPick = mount();
    expect(screen.getByText("AI")).toBeTruthy();
    expect(screen.getByText("Apps and the web")).toBeTruthy();
    // A group of one step is that step.
    await userEvent.click(screen.getByRole("option", { name: /Run an agent/ }));
    expect(onPick).toHaveBeenCalledWith(AGENT);

    await userEvent.click(screen.getByRole("option", { name: /^Slack/ }));
    const rows = screen.getAllByRole("option").map((row) => row.textContent ?? "");
    // Acting first: send before read, whatever order the catalog had.
    expect(rows.findIndex((row) => row.includes("Send a message"))).toBeLessThan(
      rows.findIndex((row) => row.includes("Read messages")),
    );
    expect(screen.getByText("Post, read and look up in Slack")).toBeTruthy();
    await userEvent.click(screen.getByRole("option", { name: /Send a message/ }));
    expect(onPick).toHaveBeenLastCalledWith(SEND);

    await userEvent.click(screen.getByRole("option", { name: "All steps" }));
    expect(screen.getByText("AI")).toBeTruthy();
  });

  it("leaves a group on Backspace in an empty search, and searches every step at once", async () => {
    const onPick = mount();
    await userEvent.click(screen.getByRole("option", { name: /^Slack/ }));
    const search = screen.getByPlaceholderText("Search steps");
    fireEvent.keyDown(search, { key: "Backspace" });
    expect(screen.getByText("AI")).toBeTruthy();

    await userEvent.type(search, "read");
    expect(screen.queryByText("AI")).toBeNull();
    expect(screen.getByText("Read messages")).toBeTruthy();
    expect(screen.getByText("Slack")).toBeTruthy();
    await userEvent.click(screen.getByRole("option", { name: /Read messages/ }));
    expect(onPick).toHaveBeenCalledWith(READ);

    await userEvent.clear(search);
    await userEvent.type(search, "zzz");
    expect(screen.getByText("No nodes match your search.")).toBeTruthy();
    // Backspace with text in the box edits the text, and stays in the results.
    fireEvent.keyDown(search, { key: "Backspace" });
    expect(screen.queryByText("AI")).toBeNull();
  });

  it("lets a row be dragged onto the canvas when the picker allows it", () => {
    mount(true);
    const row = screen.getByRole("option", { name: /Run an agent/ });
    const setData = vi.fn();
    fireEvent.dragStart(row, { dataTransfer: { setData, effectAllowed: "" } });
    expect(setData).toHaveBeenCalledWith(NODE_DRAG_MIME, expect.stringContaining("agent.run"));
  });
});
