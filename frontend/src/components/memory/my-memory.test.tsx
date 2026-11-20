import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MyMemory } from "./my-memory";

vi.mock("./my-claims", () => ({ MyClaims: () => <p>memory-list</p> }));
vi.mock("./my-notes", () => ({ MyNotes: () => <p>note-list</p> }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("memory workspace", () => {
  it("presents short memories and linked notes together", () => {
    render(<MyMemory />);
    const memory = screen.getByRole("region", { name: "viewLabel" });
    expect(memory).toContainElement(screen.getByText("memory-list"));
    expect(memory).toContainElement(screen.getByText("note-list"));
  });
});
