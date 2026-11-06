import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { PageTabs } from "./page-tabs";
import { SETTINGS_TABS } from "@/app/[locale]/(dashboard)/settings/settings-tabs";

vi.mock("@/lib/active-route", () => ({
  useActiveRoute: () => (href: string) => href === "/settings/api-keys",
}));

const TABS = [
  { labelKey: "profile", href: "/settings/profile" },
  { labelKey: "api", href: "/settings/api-keys" },
];

describe("PageTabs", () => {
  it("keeps every settings section in a visible strip when scrolling is selected", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PageTabs tabs={SETTINGS_TABS} overflow="scroll" />
      </NextIntlClientProvider>,
    );

    const strip = screen.getByRole("navigation");
    expect(strip).not.toHaveClass("hidden", "md:hidden");
    expect(screen.queryByRole("button", { name: "Section: API" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Memory" })).toHaveAttribute(
      "href",
      "/settings/memory",
    );
    expect(screen.getByRole("link", { name: "API" })).toHaveAttribute("aria-current", "page");
    expect(screen.getAllByRole("link")).toHaveLength(
      SETTINGS_TABS.filter((tab) => !tab.shellOnly).length,
    );
  });

  it("offers long section lists through a menu with the current section named", async () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PageTabs
          tabs={[
            ...TABS,
            { labelKey: "notifications", href: "/settings/notifications" },
            { labelKey: "memory", href: "/settings/memory" },
            { labelKey: "account", href: "/settings/account" },
          ]}
        />
      </NextIntlClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Section: API" }));
    expect(screen.getByRole("menuitem", { name: "Profile" })).toHaveAttribute(
      "href",
      "/settings/profile",
    );
    expect(screen.getByRole("menuitem", { name: "API" })).toHaveAttribute("aria-current", "page");
  });

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

  it("recentres the active section when its strip narrows and releases the observer", () => {
    const observers: { callback: ResizeObserverCallback; observer: ResizeObserver }[] = [];
    const disconnect = vi.fn();
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class implements ResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        observers.push({ callback, observer: this });
      }
      observe() {}
      unobserve() {}
      disconnect() {
        disconnect();
      }
    };
    const left = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockReturnValue(600);
    const width = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(80);
    const viewport = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000);
    try {
      const { unmount } = render(
        <NextIntlClientProvider locale="en" messages={messages}>
          <PageTabs tabs={TABS} overflow="scroll" />
        </NextIntlClientProvider>,
      );
      const nav = screen.getByRole("navigation");
      expect(nav.scrollLeft).toBe(140);
      viewport.mockReturnValue(380);
      observers.forEach(({ callback, observer }) => callback([], observer));
      expect(nav.scrollLeft).toBe(450);
      unmount();
      expect(disconnect).toHaveBeenCalled();
    } finally {
      globalThis.ResizeObserver = original;
      [left, width, viewport].forEach((spy) => spy.mockRestore());
    }
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

  it("leaves the desktop app's tabs out of the phone app, which has no blobby to configure", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "android",
      version: "0.1.0",
      window: "main",
      vibrancy: false,
    };
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PageTabs
          tabs={[...TABS, { labelKey: "blobby", href: "/settings/blobby", shellOnly: true }]}
        />
      </NextIntlClientProvider>,
    );
    expect(screen.queryByRole("link", { name: "Blobby" })).toBeNull();
    delete window.__AGENTICOS_SHELL__;
  });
});
