import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it } from "vitest";

import { LanguageSwitcherIcon } from "@/components/language-switcher";
import { LOCALE_COOKIE_NAME } from "@/lib/locale-routing";
import middleware from "@/middleware";

describe("LanguageSwitcherIcon", () => {
  beforeEach(() => {
    document.cookie = `${LOCALE_COOKIE_NAME}=; max-age=0; path=/`;
  });

  it("makes a chosen locale survive the next navigation", async () => {
    // The two halves of #285 in one test, because either alone still reverts:
    // the switch has to record the choice, and the middleware has to act on it
    // when a link arrives without a prefix - which most of them do.
    const user = userEvent.setup();
    render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <LanguageSwitcherIcon />
      </NextIntlClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Language" }));
    await user.click(await screen.findByText("Polski"));

    expect(document.cookie).toContain(`${LOCALE_COOKIE_NAME}=pl`);

    const nextPage = new NextRequest(new URL("https://agenticos.test/orgs"), {
      headers: new Headers({ cookie: document.cookie }),
    });
    expect(middleware(nextPage).headers.get("location")).toBe("https://agenticos.test/pl/orgs");
  });
});
