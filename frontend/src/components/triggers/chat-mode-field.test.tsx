import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatModeField } from "./chat-mode-field";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("ChatModeField", () => {
  it("says what the chosen destination means", () => {
    render(<ChatModeField value="per_run" onChange={vi.fn()} />);

    expect(screen.getByText("chatModeHint.per_run")).toBeInTheDocument();
    expect(screen.getByText("chatModeLabel")).toBeInTheDocument();
  });

  it("lets the person choose a shared read-only history", async () => {
    const change = vi.fn();
    render(<ChatModeField value="per_run" onChange={change} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "chatMode.shared" }));
    expect(change).toHaveBeenCalledWith("shared");
  });

  it("explains that a shared history is read-only", () => {
    render(<ChatModeField value="shared" onChange={vi.fn()} />);

    expect(screen.getByText("chatModeHint.shared")).toBeInTheDocument();
  });
});
