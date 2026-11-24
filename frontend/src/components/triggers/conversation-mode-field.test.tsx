import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConversationModeField } from "./conversation-mode-field";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("ConversationModeField", () => {
  it("says what the chosen mode means", () => {
    render(<ConversationModeField value="continue" onChange={vi.fn()} />);

    expect(screen.getByText("conversationModeHint.continue")).toBeInTheDocument();
    expect(screen.getByText("conversationModeLabel")).toBeInTheDocument();
  });

  it("says a fresh conversation per fire keeps fires apart", () => {
    render(<ConversationModeField value="fresh" onChange={vi.fn()} />);

    expect(screen.getByText("conversationModeHint.fresh")).toBeInTheDocument();
  });
});
