import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TypingIndicator } from "./typing-indicator";
import type { ChatPerson } from "@/types";

function person(id: string, name: string): ChatPerson {
  return { user_id: id, name, has_avatar: false, avatar_color: null };
}

describe("TypingIndicator", () => {
  it("draws nothing while nobody else is writing", () => {
    const { container } = render(<TypingIndicator people={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says who is writing, one person or several", () => {
    const { rerender } = render(<TypingIndicator people={[person("a", "Anna")]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Anna is typing");

    rerender(<TypingIndicator people={[person("a", "Anna"), person("o", "Ola")]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Anna, Ola are typing");
  });
});
