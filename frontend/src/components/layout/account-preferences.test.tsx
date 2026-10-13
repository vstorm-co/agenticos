import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppearanceMenu, LanguageMenu, VoiceGlowMenu } from "./account-preferences";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useThemeStore } from "@/stores/theme-store";
import { useVoiceGlowStore } from "@/stores/voice-glow-store";

const env = vi.hoisted(() => ({ reduced: false, mounted: true, push: vi.fn() }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("motion/react")>()),
  useReducedMotion: () => env.reduced,
}));
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
  env.reduced = false;
  env.mounted = true;
  env.push.mockClear();
  useVoiceGlowStore.setState({ style: "subtle" });
  useThemeStore.setState({ theme: "system" });
});

describe("VoiceGlowMenu", () => {
  it("says the current style on the trigger, without being opened", () => {
    inMenu(<VoiceGlowMenu />);

    expect(screen.getByRole("menuitem", { name: /Voice glow/ })).toHaveTextContent("Subtle");
  });

  it("keeps the style the person picks", async () => {
    inMenu(<VoiceGlowMenu />);
    await openSubmenu(/Voice glow/);

    expect(await screen.findByRole("menuitemradio", { name: "Subtle" })).toBeChecked();
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Off" }));

    expect(useVoiceGlowStore.getState().style).toBe("off");
  });

  it("offers nothing to pick under reduced motion, and says why", async () => {
    env.reduced = true;
    useVoiceGlowStore.setState({ style: "vivid" });
    inMenu(<VoiceGlowMenu />);

    expect(screen.getByRole("menuitem", { name: /Voice glow/ })).toHaveTextContent("Off");
    await openSubmenu(/Voice glow/);

    for (const name of ["Vivid", "Subtle", "Off"]) {
      expect(await screen.findByRole("menuitemradio", { name })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    }
    expect(screen.getByText("Off while reduced motion is on")).toBeInTheDocument();
    // The stored preference survives, for when reduced motion is turned off.
    expect(useVoiceGlowStore.getState().style).toBe("vivid");
  });

  it("names no value before mount, when the stored one is not known yet", () => {
    env.mounted = false;
    env.reduced = true;
    inMenu(<VoiceGlowMenu />);

    const trigger = screen.getByRole("menuitem", { name: /Voice glow/ });
    expect(trigger).not.toHaveTextContent("Subtle");
    expect(trigger).not.toHaveTextContent("Off");
  });
});

describe("AppearanceMenu", () => {
  it("switches the theme", async () => {
    inMenu(<AppearanceMenu />);
    expect(screen.getByRole("menuitem", { name: /Appearance/ })).toHaveTextContent("System");
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
