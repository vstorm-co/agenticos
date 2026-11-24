import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { LanguageSwitcherIcon } from "@/components/language-switcher";

describe("LanguageSwitcherIcon", () => {
  it("lists only the locales the deployment serves", async () => {
    const user = userEvent.setup();
    render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <LanguageSwitcherIcon />
      </NextIntlClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Language" }));

    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["🇬🇧English"]);
  });

  it("hands the choice to the caller when it asks for it", async () => {
    const user = userEvent.setup();
    const chosen: string[] = [];
    render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <LanguageSwitcherIcon onLocaleChange={(locale) => chosen.push(locale)} />
      </NextIntlClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Language" }));
    await user.click(await screen.findByRole("menuitem", { name: /English/ }));

    expect(chosen).toEqual(["en"]);
  });
});
