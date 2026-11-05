import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import SettingsLayout from "./layout";

let pathname = "/settings/account";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));
vi.mock("@/components/dashboard/page-tabs", () => ({ PageTabs: () => <nav /> }));

it("returns to the settings heading when the section changes, preserving the memory page title", () => {
  const scroll = vi.fn();
  const previous = HTMLElement.prototype.scrollIntoView;
  HTMLElement.prototype.scrollIntoView = scroll;
  try {
    const { rerender } = render(
      <SettingsLayout>
        <p>Account panel</p>
      </SettingsLayout>,
    );
    expect(screen.getByRole("heading", { name: "Settings" })).toBeVisible();
    expect(scroll).toHaveBeenCalledWith({ block: "start" });
    scroll.mockClear();
    pathname = "/settings/memory";
    rerender(
      <SettingsLayout>
        <p>Memory panel</p>
      </SettingsLayout>,
    );
    expect(screen.getByRole("heading", { name: "Your memory" })).toBeVisible();
    expect(scroll).toHaveBeenCalledTimes(1);
  } finally {
    HTMLElement.prototype.scrollIntoView = previous;
    pathname = "/settings/account";
  }
});
