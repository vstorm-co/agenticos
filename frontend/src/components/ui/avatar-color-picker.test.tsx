import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { AvatarColorPicker } from "./avatar-color-picker";
import { AVATAR_COLOR_COUNT } from "@/lib/avatar-color";

function renderPicker(value: number | null, onChange = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <AvatarColorPicker value={value} onChange={onChange} />
    </NextIntlClientProvider>,
  );
  return onChange;
}

describe("AvatarColorPicker", () => {
  it("offers auto plus one swatch per colour", () => {
    renderPicker(null);
    // Auto and the ten colours are all radios in one group.
    expect(screen.getAllByRole("radio")).toHaveLength(AVATAR_COLOR_COUNT + 1);
  });

  it("marks auto as chosen when no slot is set", () => {
    renderPicker(null);
    expect(screen.getByRole("radio", { name: "Automatic colour" })).toBeChecked();
  });

  it("marks the chosen slot", () => {
    renderPicker(3);
    expect(screen.getByRole("radio", { name: "Colour 3" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Automatic colour" })).not.toBeChecked();
  });

  it("reports the slot a click chose", async () => {
    const onChange = renderPicker(null);
    await userEvent.click(screen.getByRole("radio", { name: "Colour 5" }));
    expect(onChange).toHaveBeenCalledWith(5);
  });

  it("reports null when auto is chosen back", async () => {
    const onChange = renderPicker(5);
    await userEvent.click(screen.getByRole("radio", { name: "Automatic colour" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
