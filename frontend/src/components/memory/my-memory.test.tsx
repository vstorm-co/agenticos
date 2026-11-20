import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MyMemory } from "./my-memory";
import { useAgents } from "@/hooks/use-agents";

vi.mock("./my-claims", () => ({ MyClaims: () => <p>memory-list</p> }));
vi.mock("./my-notes", () => ({ MyNotes: () => <p>note-list</p> }));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: vi.fn(() => ({ agents: [] })),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => false }),
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("memory workspace", () => {
  it("shows one section at a time and switches to notes", async () => {
    const user = userEvent.setup();
    render(<MyMemory />);
    expect(useAgents).toHaveBeenCalledWith({ includeArchived: true, enabled: false });
    const memories = screen.getByRole("tab", { name: "memories" });
    const notes = screen.getByRole("tab", { name: "notes" });
    expect(memories).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("memory-list")).toBeVisible();
    expect(screen.queryByText("note-list")).toBeNull();

    await user.click(notes);

    expect(notes).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("note-list")).toBeVisible();
    expect(screen.queryByText("memory-list")).toBeNull();
  });
});
