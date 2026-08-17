import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ContextCard } from "./context-card";
import type { ContextFileSummary } from "@/types/providers";

const FILE: ContextFileSummary = {
  id: "c1",
  name: "glossary",
  description: "What the words mean.",
  format: "md",
  mode: "inject",
  enabled: true,
  size_bytes: 2048,
};

function renderCard(props: Partial<React.ComponentProps<typeof ContextCard>> = {}) {
  const onOpen = vi.fn();
  const onDelete = vi.fn();
  render(<ContextCard file={FILE} canEdit onOpen={onOpen} onDelete={onDelete} {...props} />);
  return { onOpen, onDelete };
}

describe("ContextCard", () => {
  it("shows the file's name and description", () => {
    renderCard();
    expect(screen.getByText("glossary")).toBeInTheDocument();
    expect(screen.getByText(FILE.description!)).toBeInTheDocument();
  });

  it("marks an injected file so the mode is never implicit", () => {
    renderCard();
    expect(screen.getByText("injected")).toBeInTheDocument();
  });

  it("marks a linked file", () => {
    renderCard({ file: { ...FILE, mode: "link" } });
    expect(screen.getByText("linked")).toBeInTheDocument();
  });

  it("marks a file agents are currently skipping", () => {
    renderCard({ file: { ...FILE, enabled: false } });
    expect(screen.getByText("disabled")).toBeInTheDocument();
  });

  it("stays quiet about an enabled file", () => {
    renderCard();
    expect(screen.queryByText("disabled")).not.toBeInTheDocument();
  });

  it("shows the format and size", () => {
    renderCard();
    expect(screen.getByText(/md · 2.0 KB/)).toBeInTheDocument();
  });

  it("renders without a description when there is none", () => {
    renderCard({ file: { ...FILE, description: null } });
    expect(screen.queryByText("What the words mean.")).not.toBeInTheDocument();
    expect(screen.getByText("glossary")).toBeInTheDocument();
  });

  it("opens the file when its name is clicked", async () => {
    const { onOpen, onDelete } = renderCard();
    await userEvent.click(screen.getByText("glossary"));
    expect(onOpen).toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("keeps deleting separate from opening", async () => {
    const { onOpen, onDelete } = renderCard();
    await userEvent.click(screen.getByRole("button", { name: "Delete glossary" }));
    expect(onDelete).toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("offers a viewer no way to delete a file they can still read", async () => {
    const { onOpen, onDelete } = renderCard({ canEdit: false });
    expect(screen.queryByRole("button", { name: "Delete glossary" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("glossary"));
    expect(onOpen).toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });
});
