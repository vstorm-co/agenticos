import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StartersPanel } from "./starters-panel";

describe("StartersPanel", () => {
  it("lets authors opt out of built-in first messages", async () => {
    const onShowStartersChange = vi.fn();
    render(
      <StartersPanel
        starters={[]}
        showStarters={false}
        onShowStartersChange={onShowStartersChange}
        disabled={false}
        onChange={vi.fn()}
      />,
    );
    const toggle = screen.getByRole("switch", { name: "Show suggested prompts" });
    expect(toggle).not.toBeChecked();
    expect(screen.queryByRole("list")).toBeNull();
    await userEvent.click(toggle);
    expect(onShowStartersChange).toHaveBeenCalledWith(true);
  });
  it("shows the visual fallbacks as cards and turns them into custom starters only on save", async () => {
    const onChange = vi.fn();
    render(<StartersPanel starters={[]} draws disabled={false} onChange={onChange} />);
    const preview = screen.getByRole("button", { name: /Explain it in 3D/ });
    expect(preview).toHaveTextContent(/Show me in 3D how a plane turns/);
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.click(preview);
    const dialog = screen.getByRole("dialog");
    const message = within(dialog).getByRole("textbox", { name: "Message sent on click" });
    expect(message).toHaveValue(
      "Show me in 3D how a plane turns, with sliders for pitch, roll and yaw, a play button and a reset.",
    );
    await userEvent.clear(message);
    await userEvent.type(message, "Explain a bridge in 3D.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    const [messages, icons, titles] = onChange.mock.calls[0]!;
    expect(messages).toHaveLength(4);
    expect(messages[0]).toBe("Explain a bridge in 3D.");
    expect(icons["Explain a bridge in 3D."]).toBe("sparkles");
    expect(titles["Explain a bridge in 3D."]).toBe("Explain it in 3D");
  });

  it("opens the editor from a saved starter card and keeps its metadata", async () => {
    const onChange = vi.fn();
    render(
      <StartersPanel
        starters={["One", "Two"]}
        icons={{ One: "code", Two: "mail" }}
        titles={{ One: "First", Two: "Second" }}
        disabled={false}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByText("First messages"));
    await userEvent.click(screen.getByRole("button", { name: "Edit First" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Icon for first message 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Message sent on click" }),
      "!",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(onChange).toHaveBeenLastCalledWith(
      ["One!", "Two"],
      { "One!": "search", Two: "mail" },
      { "One!": "First", Two: "Second" },
    );
  });

  it("can add a new starter once the message has text", async () => {
    const onChange = vi.fn();
    render(<StartersPanel starters={["One"]} disabled={false} onChange={onChange} />);
    await userEvent.click(screen.getByText("First messages"));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    const dialog = screen.getByRole("dialog");
    const save = within(dialog).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Message sent on click" }),
      "Two",
    );
    await userEvent.click(save);
    expect(onChange).toHaveBeenCalledWith(["One", "Two"], {}, {});
  });

  it("removes one starter without changing the others", async () => {
    const onChange = vi.fn();
    render(<StartersPanel starters={["One", "Two"]} disabled={false} onChange={onChange} />);
    await userEvent.click(screen.getByText("First messages"));
    await userEvent.click(screen.getByRole("button", { name: "Edit One" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove first message 1" }));
    expect(onChange).toHaveBeenCalledWith(["Two"], {}, {});
  });

  it("keeps a draft title local when the editor is dismissed", async () => {
    const onChange = vi.fn();
    render(<StartersPanel starters={["One"]} disabled={false} onChange={onChange} />);
    await userEvent.click(screen.getByText("First messages"));
    const edit = screen.getByRole("button", { name: "Edit One" });
    await userEvent.click(edit);
    await userEvent.type(screen.getByRole("textbox", { name: "Short title (optional)" }), "Draft");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(edit);
    expect(screen.getByRole("textbox", { name: "Short title (optional)" })).toHaveValue("");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps invalid submissions from overwriting or exceeding the configured prompts", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <StartersPanel starters={[]} disabled={false} onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    const message = screen.getByRole("textbox", { name: "Message sent on click" });
    const form = message.closest("form")!;
    fireEvent.submit(form);
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.type(message, "Draft prompt");
    rerender(
      <StartersPanel starters={["1", "2", "3", "4"]} disabled={false} onChange={onChange} />,
    );
    fireEvent.submit(form);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("offers no fifth starter", async () => {
    render(<StartersPanel starters={["1", "2", "3", "4"]} disabled={false} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("First messages"));
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
  });

  it("keeps the cards read-only for readers", async () => {
    render(<StartersPanel starters={["One"]} disabled onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("First messages"));
    expect(screen.getByRole("button", { name: "One" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
  });
});
