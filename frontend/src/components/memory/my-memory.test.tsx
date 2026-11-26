import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MyMemory } from "./my-memory";
import { useAgents } from "@/hooks/use-agents";
import { useOrgStore } from "@/stores";

const can = vi.fn(() => false);
const scopeOf = vi.fn(() => "all");
vi.mock("./memory-object-library", () => ({
  MemoryObjectLibrary: ({
    library,
    initialObject,
  }: {
    library: string;
    initialObject?: string;
  }) => (
    <p>
      {library} objects {initialObject}
    </p>
  ),
  SharedMemoryClaims: () => <p>shared-claim-list</p>,
  SharedMemoryNotes: () => <p>shared-note-list</p>,
}));

vi.mock("./my-claims", () => ({ MyClaims: () => <p>memory-list</p> }));
vi.mock("./my-notes", () => ({ MyNotes: () => <p>note-list</p> }));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: vi.fn(() => ({ agents: [] })),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can, scopeOf }),
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

it("opens a shared object deep link, switches libraries and discards the link on tenant change", async () => {
  const originalOrg = useOrgStore.getState().activeOrgId;
  can.mockReturnValue(true);
  try {
    useOrgStore.setState({ activeOrgId: "initial" });
    const user = userEvent.setup();
    render(<MyMemory initialLibrary="organization" initialObject="object-1" />);
    expect(screen.getByText("organization objects object-1")).toBeVisible();
    expect(useAgents).toHaveBeenCalledWith({ includeArchived: true, enabled: true });
    await user.click(screen.getByRole("button", { name: "claims" }));
    expect(screen.getByText("shared-claim-list")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "personal" }));
    await user.click(screen.getByRole("button", { name: "objects" }));
    expect(screen.getByText("personal objects")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "organization" }));
    expect(screen.getByText("organization objects")).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "notes" }));
    expect(screen.getByText("shared-note-list")).toBeVisible();
    act(() => useOrgStore.setState({ activeOrgId: "second" }));
    expect(screen.getByText("memory-list")).toBeVisible();
  } finally {
    can.mockReturnValue(false);
    act(() => useOrgStore.setState({ activeOrgId: originalOrg }));
  }
});
