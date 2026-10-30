import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../messages/en.json";
import { ListFilters } from "./list-filters";

function mount(active: number, compact = false) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ListFilters active={active} compact={compact}>
        <select aria-label="Status" />
      </ListFilters>
    </NextIntlClientProvider>,
  );
}

describe("ListFilters", () => {
  it("keeps the compact catalog button named and linked to its fields", () => {
    mount(1, true);
    const button = screen.getByRole("button", { name: "Filters 1" });
    const id = button.getAttribute("aria-controls");
    expect(id).toBeTruthy();
    expect(document.getElementById(id!)).toContainElement(
      screen.getByRole("combobox", { hidden: true }),
    );
  });

  it("keeps the filters folded on every screen until its button opens them", () => {
    mount(0);
    const button = screen.getByRole("button", { name: /Filters/ });
    const holder = screen.getByLabelText("Status").parentElement!;
    expect(holder).toHaveAttribute("hidden");
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);

    expect(holder).not.toHaveAttribute("hidden");
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("counts the filters that are set, and shows none when none are", () => {
    const { unmount } = mount(0);
    expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
    unmount();

    mount(3);
    expect(screen.getByRole("button", { name: "Filters 3" })).toBeInTheDocument();
  });
});
