import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { scrollWithin } from "@/lib/scroll-within";
import SettingsLayout from "./layout";

vi.mock("@/lib/scroll-within", () => ({ scrollWithin: vi.fn() }));
vi.mock("@/lib/motion", () => ({ glideOrJump: () => "smooth" }));

let pathname = "/settings/account";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));
vi.mock("@/components/dashboard/page-tabs", () => ({ PageTabs: () => <nav /> }));

it("returns to the settings heading when the section changes, preserving the memory page title", () => {
  const scroll = vi.mocked(scrollWithin);
  const previous = HTMLElement.prototype.scrollIntoView;

  try {
    const { rerender } = render(
      <SettingsLayout>
        <p>Account panel</p>
      </SettingsLayout>,
    );
    expect(screen.getByRole("heading", { name: "Settings" })).toBeVisible();
    expect(scroll).toHaveBeenCalledWith(expect.any(HTMLElement), "start", "smooth");
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
