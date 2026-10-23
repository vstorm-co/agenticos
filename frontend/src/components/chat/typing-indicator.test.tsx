import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TypingIndicator } from "./typing-indicator";
import type { ChatPerson } from "@/types";

function person(id: string, name: string): ChatPerson {
  return { user_id: id, name, has_avatar: false, avatar_color: null };
}

describe("TypingIndicator", () => {
  it("keeps an empty live region while nobody else is writing", () => {
    // Mounted with nothing in it, so the first typist is announced as a change.
    render(<TypingIndicator people={[]} />);
    const region = screen.getByRole("status");
    expect(region).toBeEmptyDOMElement();
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("announces the first typist inside the region that was already there", () => {
    const { rerender } = render(<TypingIndicator people={[]} />);
    const region = screen.getByRole("status");

    rerender(<TypingIndicator people={[person("a", "Anna")]} />);

    expect(screen.getByRole("status")).toBe(region);
    expect(region).toHaveTextContent("Anna is typing");
  });

  it("says who is writing, one person or several", () => {
    const { rerender } = render(<TypingIndicator people={[person("a", "Anna")]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Anna is typing");

    rerender(<TypingIndicator people={[person("a", "Anna"), person("o", "Ola")]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Anna, Ola are typing");
  });
});
