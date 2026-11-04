import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppearanceMenu, LanguageMenu } from "./account-preferences";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useThemeStore } from "@/stores/theme-store";

const env = vi.hoisted(() => ({ mounted: true, push: vi.fn() }));

vi.mock("@/hooks/use-mounted", () => ({ useMounted: () => env.mounted }));
vi.mock("@/lib/locale-navigation", () => ({
  usePathname: () => "/agents",
  useRouter: () => ({ push: env.push }),
}));

/** The account menu, open, holding one submenu. */
function inMenu(submenu: ReactNode) {
  return render(
    <DropdownMenu open>
      <DropdownMenuTrigger>account</DropdownMenuTrigger>
      <DropdownMenuContent>{submenu}</DropdownMenuContent>
    </DropdownMenu>,
  );
}

async function openSubmenu(name: RegExp) {
  await userEvent.click(screen.getByRole("menuitem", { name }));
}

beforeEach(() => {
  env.mounted = true;
  env.push.mockClear();
  useThemeStore.setState({ theme: "system", look: "standard" });
});

describe("AppearanceMenu", () => {
  it("switches the theme", async () => {
    inMenu(<AppearanceMenu />);
    expect(screen.getByRole("menuitem", { name: /Appearance/ })).toHaveTextContent("Standard");
    await openSubmenu(/Appearance/);

    await userEvent.click(await screen.findByRole("menuitemradio", { name: "Dark" }));

    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("names no theme before mount", () => {
    env.mounted = false;
    useThemeStore.setState({ theme: "dark" });
    inMenu(<AppearanceMenu />);

    expect(screen.getByRole("menuitem", { name: /Appearance/ })).not.toHaveTextContent("Dark");
  });

  it.each(["Standard", "Glass", "Graphite", "Midnight", "Paper"])(
    "selects %s without changing the light/dark preference",
    async (name) => {
      useThemeStore.setState({ theme: "dark", look: "paper" });
      inMenu(<AppearanceMenu />);
      expect(screen.getByRole("menuitem", { name: /Appearance/ })).toHaveTextContent("Paper");
      await openSubmenu(/Appearance/);
      expect(screen.getByRole("menuitemradio", { name: "Paper" })).toBeChecked();

      await userEvent.click(screen.getByRole("menuitemradio", { name }));

      expect(useThemeStore.getState().look).toBe(name.toLowerCase());
      expect(useThemeStore.getState().theme).toBe("dark");
    },
  );

  it("lets the keyboard select a style", async () => {
    inMenu(<AppearanceMenu />);
    await openSubmenu(/Appearance/);
    screen.getByRole("menuitemradio", { name: "Standard" }).focus();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(useThemeStore.getState().look).toBe("glass");
  });

  it("checks no style before mount", async () => {
    env.mounted = false;
    useThemeStore.setState({ look: "midnight" });
    inMenu(<AppearanceMenu />);
    await openSubmenu(/Appearance/);
    for (const item of screen.getAllByRole("menuitemradio")) expect(item).not.toBeChecked();
  });
});

describe("LanguageMenu", () => {
  it("switches the language through the locale-aware router", async () => {
    inMenu(<LanguageMenu />);
    expect(screen.getByRole("menuitem", { name: /Language/ })).toHaveTextContent("English");
    await openSubmenu(/Language/);

    await userEvent.click(await screen.findByRole("menuitemradio", { name: /Polski/ }));

    expect(env.push).toHaveBeenCalledWith("/agents", { locale: "pl" });
  });
});
