import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ContextGallery } from "./context-gallery";
import type { ContextFileSummary } from "@/types/providers";

function file(overrides: Partial<ContextFileSummary> = {}): ContextFileSummary {
  return {
    id: "c1",
    name: "glossary",
    description: "What the words mean.",
    format: "md",
    mode: "inject",
    enabled: true,
    size_bytes: 100,
    ...overrides,
  };
}

describe("ContextGallery", () => {
  it("searches descriptions, because that is what a file is chosen on", async () => {
    render(
      <ContextGallery
        files={Array.from({ length: 9 }, (_, i) =>
          file({ id: `c${i}`, name: `file-${i}`, description: i === 3 ? "Refunds." : "Other." }),
        )}
        total={9}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    await userEvent.type(screen.getByLabelText("Search context files…"), "refunds");
    expect(screen.getByRole("checkbox", { name: "file-3" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "file-0" })).toBeNull();
  });

  it("searches a file that has no description without crashing", async () => {
    render(
      <ContextGallery
        files={[
          file({ id: "c0", name: "no-desc", description: null }),
          ...Array.from({ length: 8 }, (_, i) => file({ id: `c${i + 1}`, name: `file-${i}` })),
        ]}
        total={9}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    await userEvent.type(screen.getByLabelText("Search context files…"), "no-desc");
    expect(screen.getByRole("checkbox", { name: "no-desc" })).toBeInTheDocument();
  });

  it("shows the mode so the author knows what attaching one costs", () => {
    render(
      <ContextGallery
        files={[file(), file({ id: "c2", name: "runbook", mode: "link" })]}
        total={2}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("injected")).toBeInTheDocument();
    expect(screen.getByText("linked")).toBeInTheDocument();
  });

  it("names a selected file the organization no longer has", () => {
    render(
      <ContextGallery files={[file()]} total={1} selectedIds={["c1", "gone"]} onToggle={vi.fn()} />,
    );
    expect(screen.getByText(/no longer has/)).toBeInTheDocument();
  });

  it("says nothing about missing files when given only a page", () => {
    render(
      <ContextGallery
        files={[file()]}
        total={80}
        selectedIds={["c1", "on-page-two"]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.queryByText(/no longer has/)).toBeNull();
  });

  it("sends somebody to add one when the organization has none", () => {
    render(<ContextGallery files={[]} total={0} selectedIds={[]} onToggle={vi.fn()} />);
    expect(screen.getByText("This organization has no context files yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add one/ })).toBeInTheDocument();
  });

  it("says which files are attached", () => {
    render(
      <ContextGallery
        files={[file(), file({ id: "c2", name: "escalation" })]}
        total={2}
        selectedIds={["c2"]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "escalation" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "glossary" })).not.toBeChecked();
  });

  it("attaches the file that was pressed", async () => {
    const onToggle = vi.fn();
    render(<ContextGallery files={[file()]} total={1} selectedIds={[]} onToggle={onToggle} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "glossary" }));
    expect(onToggle).toHaveBeenCalledWith("c1");
  });

  it("attaches nothing for somebody who may not edit the spec", async () => {
    const onToggle = vi.fn();
    render(
      <ContextGallery files={[file()]} total={1} selectedIds={[]} onToggle={onToggle} disabled />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "glossary" }));
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("marks a file that is switched off", () => {
    render(
      <ContextGallery
        files={[file({ enabled: false })]}
        total={1}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("disabled")).toBeInTheDocument();
  });

  it("renders a file with no description without crashing", () => {
    render(
      <ContextGallery
        files={[file({ description: null })]}
        total={1}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "glossary" })).toBeInTheDocument();
  });

  it("counts more than one missing file in the plural", () => {
    render(
      <ContextGallery
        files={[file()]}
        total={1}
        selectedIds={["gone-1", "gone-2"]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText(/2 context files this organization no longer has/)).toBeInTheDocument();
  });

  it("uses the singular for a single missing file", () => {
    render(<ContextGallery files={[file()]} total={1} selectedIds={["gone"]} onToggle={vi.fn()} />);
    expect(screen.getByText(/1 context file this organization no longer has/)).toBeInTheDocument();
  });

  it("offers no search for a list short enough to read", () => {
    render(<ContextGallery files={[file()]} total={1} selectedIds={[]} onToggle={vi.fn()} />);
    expect(screen.queryByLabelText("Search context files…")).toBeNull();
  });
});
