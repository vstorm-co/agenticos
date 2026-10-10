import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ContextCard } from "./context-card";
import type { ContextFileSummary } from "@/types/providers";

// Its own spec covers the picker; a card only has to offer it for the right thing.
vi.mock("@/components/agents/add-to-agent", () => ({
  AddToAgent: ({ resource }: { resource: { kind: string; id: string } }) => (
    <span>{`add-to-agent ${resource.kind} ${resource.id}`}</span>
  ),
}));

const FILE: ContextFileSummary = {
  id: "c1",
  name: "glossary",
  description: "What the words mean.",
  format: "md",
  mode: "inject",
  enabled: true,
  visibility: "org",
  size_bytes: 2048,
  excerpt: "# Glossary\n\nARR - annual recurring revenue",
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

  it("reads a markdown body's opening as a page", () => {
    renderCard();

    expect(screen.getByText("Glossary")).toBeInTheDocument();
    expect(screen.getByText("ARR - annual recurring revenue")).toBeInTheDocument();
  });

  it("shows a non-markdown body as it is, and a blank page for an empty one", () => {
    const { rerender } = render(
      <ContextCard
        file={{ ...FILE, format: "csv", excerpt: "term,meaning\nARR,revenue" }}
        canEdit={false}
        onOpen={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText(/term,meaning/)).toBeInTheDocument();

    rerender(
      <ContextCard
        file={{ ...FILE, excerpt: "" }}
        canEdit={false}
        onOpen={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByText(/term,meaning/)).toBeNull();
    expect(screen.queryByText("Glossary")).toBeNull();
  });
  it("offers to give the file to an agent", () => {
    renderCard();
    expect(screen.getByText("add-to-agent context c1")).toBeInTheDocument();
  });
});
