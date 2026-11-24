import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "@/stores/auth-store";
import { useThemeStore } from "@/stores/theme-store";
import { useMotionStore } from "@/stores/motion-store";
import { useVoiceGlowStore } from "@/stores/voice-glow-store";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";
import type { User } from "@/types";
import { resetSessionState, resetTenantState } from "@/stores/session-reset";
import {
  adoptAccountAppearance,
  appearanceGeneration,
  resetAccountAppearance,
} from "./account-appearance";
import { DEFAULT_APPEARANCE, userAppearanceSchema } from "./user-appearance";

const alice = { id: "alice" } as User;
beforeEach(() => {
  resetAccountAppearance();
  useAuthStore.setState({ user: alice, sessionOwnerId: alice.id });
});

describe("account appearance", () => {
  it("applies only trusted tokens to the current person's stores and variables", () => {
    expect(
      adoptAccountAppearance("alice", appearanceGeneration(), {
        ...DEFAULT_APPEARANCE,
        theme: "dark",
        look: "paper",
        accent: "blue",
        radius: "rounded",
        text_size: "large",
        motion: "reduce",
        voice_glow: "off",
        workflow_nodes: "simple",
      }),
    ).toBe(true);
    expect(useThemeStore.getState()).toMatchObject({ theme: "dark", look: "paper" });
    expect(useMotionStore.getState().motion).toBe("reduce");
    expect(useVoiceGlowStore.getState().style).toBe("off");
    expect(useWorkflowNodeStyleStore.getState().style).toBe("simple");
    expect(document.documentElement.style.getPropertyValue("--brand-h")).toBe("255");
    expect(document.documentElement.style.getPropertyValue("--radius")).toBe("1rem");
    expect(document.documentElement.style.getPropertyValue("--radius-lg")).toBe("1rem");
    expect(document.documentElement.style.getPropertyValue("--color-primary")).toContain("255");
    expect(document.documentElement.style.fontSize).toBe("112.5%");
  });

  it("preserves appearance across organization switches, and clears it on account reset", () => {
    adoptAccountAppearance("alice", appearanceGeneration(), {
      ...DEFAULT_APPEARANCE,
      theme: "dark",
      text_size: "large",
    });
    resetTenantState();
    expect(useThemeStore.getState().theme).toBe("dark");
    resetSessionState();
    expect(useThemeStore.getState().theme).toBe("system");
    expect(document.documentElement.style.fontSize).toBe("");
    expect(document.documentElement.style.getPropertyValue("--color-primary")).toBe("");
    expect(document.documentElement.style.getPropertyValue("--radius-lg")).toBe("");
  });

  it("ignores late answers from a previous account or previous session of the same account", () => {
    const epoch = appearanceGeneration();
    useAuthStore.setState({ user: { id: "bob" } as User });
    expect(adoptAccountAppearance("alice", epoch, { ...DEFAULT_APPEARANCE, theme: "dark" })).toBe(
      false,
    );
    resetAccountAppearance();
    useAuthStore.setState({ user: alice });
    expect(adoptAccountAppearance("alice", epoch, { ...DEFAULT_APPEARANCE, theme: "dark" })).toBe(
      false,
    );
    expect(useThemeStore.getState().theme).toBe("system");
  });

  it("refuses CSS-like and unknown values before they reach a style property", () => {
    for (const changes of [
      { accent: "url(https://example.com)" },
      { radius: "999px" },
      { text_size: "0px" },
    ]) {
      expect(userAppearanceSchema.safeParse({ ...DEFAULT_APPEARANCE, ...changes }).success).toBe(
        false,
      );
    }
  });
});
