import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { PageTabs } from "./page-tabs";

vi.mock("@/lib/active-route", () => ({
  useActiveRoute: () => (href: string) => href === "/settings/api-keys",
}));

const TABS = [
  { labelKey: "profile", href: "/settings/profile" },
  { labelKey: "api", href: "/settings/api-keys" },
];

describe("PageTabs", () => {
  it("marks the active tab and scrolls the strip, not the page, to centre it", () => {
    const offsetLeft = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockReturnValue(600);
    const offsetWidth = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(80);
    const clientWidth = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(380);

    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PageTabs tabs={TABS} />
      </NextIntlClientProvider>,
    );

    expect(screen.getByRole("link", { name: "API" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Profile" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("navigation").scrollLeft).toBe(450);
    [offsetLeft, offsetWidth, clientWidth].forEach((spy) => spy.mockRestore());
  });

  it("leaves the strip where it is when no tab is active", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PageTabs tabs={[{ labelKey: "profile", href: "/settings/profile" }]} />
      </NextIntlClientProvider>,
    );

    expect(screen.getByRole("navigation").scrollLeft).toBe(0);
  });

  it("shows the desktop app's tabs only inside the app", () => {
    const tabs = [...TABS, { labelKey: "blobby", href: "/settings/blobby", shellOnly: true }];
    const { unmount } = render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PageTabs tabs={tabs} />
      </NextIntlClientProvider>,
    );
    expect(screen.queryByRole("link", { name: "Blobby" })).toBeNull();
    unmount();

    window.__AGENTICOS_SHELL__ = {
      platform: "macos",
      version: "0.2.0",
      window: "main",
      vibrancy: true,
    };
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PageTabs tabs={tabs} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByRole("link", { name: "Blobby" })).toBeInTheDocument();
    delete window.__AGENTICOS_SHELL__;
  });
});
