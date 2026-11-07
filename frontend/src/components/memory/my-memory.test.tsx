import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MyMemory } from "./my-memory";

vi.mock("./my-claims", () => ({ MyClaims: () => <p>memory-list</p> }));
vi.mock("./my-notes", () => ({ MyNotes: () => <p>note-list</p> }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("memory workspace", () => {
  it("opens on memories and keeps the other store out of the empty state", async () => {
    render(<MyMemory />);
    expect(screen.getByText("memory-list")).toBeVisible();
    expect(screen.queryByText("note-list")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "notes" }));
    expect(screen.getByText("note-list")).toBeVisible();
    expect(screen.queryByText("memory-list")).not.toBeInTheDocument();
  });
});
