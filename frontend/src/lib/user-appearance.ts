import { z } from "zod";

export const ACCENTS = ["default", "blue", "violet", "green", "amber", "rose"] as const;
export const RADII = ["default", "square", "rounded"] as const;
export const TEXT_SIZES = ["default", "large"] as const;

/** Closed tokens only. Neither API data nor agents can supply executable CSS. */
export const userAppearanceSchema = z.object({
  theme: z.enum(["light", "dark", "system"]),
  look: z.enum(["standard", "glass", "graphite", "midnight", "paper"]),
  accent: z.enum(ACCENTS),
  radius: z.enum(RADII),
  text_size: z.enum(TEXT_SIZES),
  motion: z.enum(["system", "reduce", "full"]),
  voice_glow: z.enum(["vivid", "subtle", "off"]),
  workflow_nodes: z.enum(["colour", "simple"]),
});

export type UserAppearance = z.infer<typeof userAppearanceSchema>;
export const DEFAULT_APPEARANCE: UserAppearance = {
  theme: "system",
  look: "standard",
  accent: "default",
  radius: "default",
  text_size: "default",
  motion: "system",
  voice_glow: "subtle",
  workflow_nodes: "colour",
};

export const ACCENT_HUES: Record<UserAppearance["accent"], number> = {
  default: 265,
  blue: 255,
  violet: 295,
  green: 155,
  amber: 80,
  rose: 15,
};
export const APPEARANCE_RADII: Record<UserAppearance["radius"], string> = {
  default: "0.5rem",
  square: "0.125rem",
  rounded: "1rem",
};

/** Theme variables are produced from trusted maps, never interpolated input. */
export function applyAppearanceVariables(preferences: UserAppearance): void {
  const root = document.documentElement;
  root.style.setProperty("--brand-h", String(ACCENT_HUES[preferences.accent]));
  root.style.setProperty("--brand-c", preferences.accent === "default" ? "0" : "0.16");
  const actionRoles = {
    "--color-primary": 48,
    "--color-primary-hover": 42,
    "--color-primary-active": 36,
    "--color-action": 48,
    "--color-action-hover": 42,
    "--color-action-active": 36,
  };
  for (const [name, lightness] of Object.entries(actionRoles)) {
    if (preferences.accent === "default") root.style.removeProperty(name);
    else
      root.style.setProperty(name, `oklch(${lightness}% 0.16 ${ACCENT_HUES[preferences.accent]})`);
  }
  for (const name of ["--color-primary-foreground", "--color-action-foreground"]) {
    if (preferences.accent === "default") root.style.removeProperty(name);
    else root.style.setProperty(name, "white");
  }
  const radii =
    preferences.radius === "rounded"
      ? [0.5, 0.75, 1, 1.25, 1.5, 2]
      : [0.0625, 0.125, 0.1875, 0.25, 0.375, 0.5];
  ["sm", "md", "lg", "xl", "2xl", "3xl"].forEach((size, index) => {
    if (preferences.radius === "default") root.style.removeProperty(`--radius-${size}`);
    else root.style.setProperty(`--radius-${size}`, `${radii[index]}rem`);
  });
  root.style.setProperty("--radius", APPEARANCE_RADII[preferences.radius]);
  root.style.setProperty(
    "--radius-card",
    preferences.radius === "rounded"
      ? "1.25rem"
      : preferences.radius === "square"
        ? "0.25rem"
        : "0.75rem",
  );
  if (preferences.text_size === "large") root.style.fontSize = "112.5%";
  else root.style.removeProperty("font-size");
}
