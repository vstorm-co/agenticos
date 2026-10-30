import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopState } from "@/lib/desktop/commands";

import { DESKTOP_STATE, MAC_MAIN } from "./fixtures";
import { ShortcutSettings } from "./shortcut-settings";

const env = vi.hoisted(() => ({
  shell: null as unknown,
  state: null as unknown,
  change: { mutate: vi.fn(), isPending: false },
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () => ({ data: env.state, error: null }),
  useSetShortcut: () => env.change,
}));

beforeEach(() => {
  env.shell = MAC_MAIN;
  env.state = DESKTOP_STATE;
  env.change.mutate = vi.fn((_value, options?: { onSuccess?: () => void }) =>
    options?.onSuccess?.(),
  );
});

const field = (name: string) => screen.getByRole("textbox", { name });

describe("ShortcutSettings", () => {
  it("shows each binding as the keyboard draws it", () => {
    render(<ShortcutSettings />);
    expect(field("Quick ask")).toHaveValue("⌥Space");
    expect(field("Screenshot to a new chat")).toHaveValue("⌘⇧A");
  });

  it("offers opening the main console as a configurable global shortcut", () => {
    env.state = {
      ...DESKTOP_STATE,
      shortcuts: [{ action: "open_console", accelerator: "CmdOrCtrl+Shift+O", problem: null }],
    } satisfies DesktopState;
    render(<ShortcutSettings />);
    expect(field("Open AgenticOS")).toHaveValue("⌘⇧O");
  });

  it("records the next combination pressed in a field and saves it", async () => {
    render(<ShortcutSettings />);
    await userEvent.click(field("Quick ask"));
    expect(field("Quick ask")).toHaveAttribute("placeholder", "Press a combination");
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(field("Quick ask")).toHaveValue("⌃K");

    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]!);

    expect(env.change.mutate).toHaveBeenCalledWith(
      { action: "quick_ask", accelerator: "Ctrl+K" },
      expect.any(Object),
    );
  });

  it("ignores a bare key, lets Tab move on, and forgets the recording on Escape", async () => {
    render(<ShortcutSettings />);
    await userEvent.click(field("Quick ask"));
    await userEvent.keyboard("k");
    expect(field("Quick ask")).toHaveValue("⌥Space");
    await userEvent.keyboard("{Control>}k{/Control}{Escape}");
    expect(field("Quick ask")).toHaveValue("⌥Space");
    expect(field("Quick ask")).not.toHaveFocus();
    await userEvent.click(field("Quick ask"));
    await userEvent.tab();
    expect(field("Quick ask")).not.toHaveFocus();
    expect(screen.getAllByRole("button", { name: "Save" })[0]).toBeDisabled();
  });

  it("switches a shortcut off, and says which one another application holds", async () => {
    env.state = {
      ...DESKTOP_STATE,
      shortcuts: [
        { action: "quick_ask", accelerator: "Alt+Space", problem: "held" },
        { action: "screenshot_chat", accelerator: null, problem: null },
      ],
    } satisfies DesktopState;
    env.shell = { ...MAC_MAIN, platform: "windows" };
    render(<ShortcutSettings />);
    expect(screen.getByRole("alert")).toHaveTextContent("Alt+Space could not be bound");
    expect(field("Screenshot to a new chat")).toHaveAttribute("placeholder", "Not bound");
    expect(screen.getAllByRole("button", { name: "Clear" })[1]).toBeDisabled();

    await userEvent.click(screen.getAllByRole("button", { name: "Clear" })[0]!);

    expect(env.change.mutate).toHaveBeenCalledWith(
      { action: "quick_ask", accelerator: null },
      expect.any(Object),
    );
  });
});
