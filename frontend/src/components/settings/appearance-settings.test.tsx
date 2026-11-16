import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_APPEARANCE, type UserAppearance } from "@/lib/user-appearance";
import { useThemeStore } from "@/stores/theme-store";
import { AppearanceSettings } from "./appearance-settings";

const env = vi.hoisted(() => ({
  owner: "alice",
  preferences: undefined as UserAppearance | undefined,
  error: null as Error | null,
  pending: false,
  save: vi.fn(),
  reset: vi.fn(),
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-user-appearance", () => ({ useUserAppearance: () => env }));

function group(name: string) {
  return screen.getByRole("radiogroup", { name });
}

beforeEach(() => {
  env.owner = "alice";
  env.preferences = { ...DEFAULT_APPEARANCE };
  env.error = null;
  env.pending = false;
  env.save.mockReset().mockResolvedValue({});
  env.reset.mockReset().mockResolvedValue({});
  useThemeStore.setState({ theme: "system", look: "standard" });
});

describe("AppearanceSettings", () => {
  it("previews choices without saving or dressing the console until Apply", async () => {
    const { container } = render(<AppearanceSettings />);
    expect(container.querySelector('[data-tour="settings-appearance"]')).toHaveTextContent(
      "Appearance",
    );
    await userEvent.click(within(group("Theme")).getByRole("radio", { name: "Dark" }));
    await userEvent.click(within(group("Accent colour")).getByRole("radio", { name: "Blue" }));
    expect(screen.getByRole("region", { name: "Live preview" })).toBeInTheDocument();
    expect(useThemeStore.getState().theme).toBe("system");
    expect(env.save).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(env.save).toHaveBeenCalledWith({ theme: "dark", accent: "blue" });
  });

  it("discards a preview without writing account preferences", async () => {
    render(<AppearanceSettings />);
    await userEvent.click(within(group("Style")).getByRole("radio", { name: /Midnight/ }));
    await userEvent.click(screen.getByRole("button", { name: "Discard preview" }));
    expect(within(group("Style")).getByRole("radio", { name: /Standard/ })).toBeChecked();
    expect(env.save).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  it("keeps an unsuccessful save available to retry", async () => {
    env.save.mockRejectedValue(new Error("offline"));
    render(<AppearanceSettings />);
    await userEvent.click(within(group("Text size")).getByRole("radio", { name: "Large" }));
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(within(group("Text size")).getByRole("radio", { name: "Large" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
  });

  it("resets the account explicitly and clears a pending preview", async () => {
    render(<AppearanceSettings />);
    await userEvent.click(within(group("Theme")).getByRole("radio", { name: "Dark" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(env.reset).toHaveBeenCalledOnce();
    expect(within(group("Theme")).getByRole("radio", { name: "System" })).toBeChecked();
  });

  it("keeps a preview after a refused reset and lets the person retry", async () => {
    env.reset.mockRejectedValueOnce(new Error("reset unavailable"));
    render(<AppearanceSettings />);
    await userEvent.click(within(group("Theme")).getByRole("radio", { name: "Dark" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(within(group("Theme")).getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
    expect(useThemeStore.getState().theme).toBe("system");

    await userEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(env.reset).toHaveBeenCalledTimes(2);
    expect(within(group("Theme")).getByRole("radio", { name: "System" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  it("keeps corner changes in the preview until they are applied", async () => {
    render(<AppearanceSettings />);
    await userEvent.click(within(group("Corners")).getByRole("radio", { name: "Rounded" }));
    expect(within(group("Corners")).getByRole("radio", { name: "Rounded" })).toBeChecked();
    expect(env.save).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(env.save).toHaveBeenCalledWith({ radius: "rounded" });
  });

  it("does not let one person's unsaved preview follow another account", async () => {
    const view = render(<AppearanceSettings />);
    await userEvent.click(within(group("Theme")).getByRole("radio", { name: "Dark" }));
    env.owner = "bob";
    env.preferences = { ...DEFAULT_APPEARANCE, look: "paper" };
    view.rerender(<AppearanceSettings />);
    expect(within(group("Theme")).getByRole("radio", { name: "System" })).toBeChecked();
    expect(within(group("Style")).getByRole("radio", { name: /Paper/ })).toBeChecked();
    expect(env.save).not.toHaveBeenCalled();
  });

  it("does not expose editable defaults while saved preferences are unavailable", async () => {
    env.preferences = undefined;
    env.error = new Error("offline");
    render(<AppearanceSettings />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(env.refetch).toHaveBeenCalledOnce();
  });

  it("saves motion, glow and workflow choices with the same account", async () => {
    render(<AppearanceSettings />);
    await userEvent.click(within(group("Motion")).getByRole("radio", { name: "Reduce" }));
    await userEvent.click(within(group("Voice glow")).getByRole("radio", { name: "Vivid" }));
    await userEvent.click(within(group("Workflow steps")).getByRole("radio", { name: "Simple" }));
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(env.save).toHaveBeenCalledWith({
      motion: "reduce",
      voice_glow: "vivid",
      workflow_nodes: "simple",
    });
  });
});
