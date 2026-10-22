import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMotionStore } from "@/stores/motion-store";
import { useThemeStore } from "@/stores/theme-store";
import { useVoiceGlowStore } from "@/stores/voice-glow-store";

import { AppearanceSettings } from "./appearance-settings";

const env = vi.hoisted(() => ({ reduced: false, mounted: true }));

vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => env.reduced }));
vi.mock("@/hooks/use-mounted", () => ({ useMounted: () => env.mounted }));

function group(name: string) {
  return screen.getByRole("radiogroup", { name });
}

beforeEach(() => {
  env.reduced = false;
  env.mounted = true;
  useThemeStore.setState({ theme: "system" });
  useVoiceGlowStore.setState({ style: "subtle" });
  useMotionStore.setState({ motion: "system" });
});

describe("AppearanceSettings", () => {
  it("anchors its tour stop on the card", () => {
    const { container } = render(<AppearanceSettings />);

    expect(container.querySelector('[data-tour="settings-appearance"]')).toHaveTextContent(
      "Appearance",
    );
  });

  it("switches the theme the account menu also switches", async () => {
    render(<AppearanceSettings />);
    expect(within(group("Theme")).getByRole("radio", { name: "System" })).toBeChecked();

    await userEvent.click(within(group("Theme")).getByRole("radio", { name: "Dark" }));

    expect(useThemeStore.getState().theme).toBe("dark");
    expect(within(group("Theme")).getByRole("radio", { name: "Dark" })).toBeChecked();
  });

  it("keeps the voice glow style the person picks, and says what it is", async () => {
    render(<AppearanceSettings />);
    expect(
      screen.getByText("How the chat box reacts to your voice while dictating"),
    ).toBeInTheDocument();

    await userEvent.click(within(group("Voice glow")).getByRole("radio", { name: "Vivid" }));

    expect(useVoiceGlowStore.getState().style).toBe("vivid");
  });

  it("sets the motion preference", async () => {
    render(<AppearanceSettings />);
    expect(within(group("Motion")).getByRole("radio", { name: "System" })).toBeChecked();

    await userEvent.click(within(group("Motion")).getByRole("radio", { name: "Reduce" }));

    expect(useMotionStore.getState().motion).toBe("reduce");
  });

  it("offers no glow under reduced motion, says why, and keeps the stored style", () => {
    env.reduced = true;
    useVoiceGlowStore.setState({ style: "vivid" });
    render(<AppearanceSettings />);

    const glow = group("Voice glow");
    expect(within(glow).getByRole("radio", { name: "Off" })).toBeChecked();
    for (const radio of within(glow).getAllByRole("radio")) expect(radio).toBeDisabled();
    expect(screen.getByText("Off while reduced motion is on")).toBeInTheDocument();
    expect(useVoiceGlowStore.getState().style).toBe("vivid");
    // Motion itself stays reachable - it is how reduced motion is turned off.
    expect(within(group("Motion")).getByRole("radio", { name: "Full" })).toBeEnabled();
  });

  it("checks nothing before mount, when the stored values are not known yet", () => {
    env.mounted = false;
    render(<AppearanceSettings />);

    for (const radio of screen.getAllByRole("radio")) expect(radio).not.toBeChecked();
  });
});
