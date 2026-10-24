import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../messages/en.json";
import { PhoneFilters } from "./phone-filters";

function mount(active: number) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <PhoneFilters active={active}>
        <select aria-label="Status" />
      </PhoneFilters>
    </NextIntlClientProvider>,
  );
}

describe("PhoneFilters", () => {
  it("keeps the filters folded on a phone until its button opens them", () => {
    mount(0);
    const button = screen.getByRole("button", { name: /Filters/ });
    const holder = screen.getByRole("combobox", { name: "Status" }).parentElement!;
    expect(holder).toHaveClass("max-sm:hidden");
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);

    expect(holder).not.toHaveClass("max-sm:hidden");
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
