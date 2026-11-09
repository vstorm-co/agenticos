"use client";

import { Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";

import { IconButton } from "@/components/ui";
import type { ArtifactTheme } from "@/types/artifact";

/** Only the embedded app's preference; no console CSS or document rewrite. */
export function ArtifactThemeToggle({
  theme,
  onChange,
}: {
  theme: ArtifactTheme;
  onChange: (theme: ArtifactTheme) => void;
}) {
  const t = useTranslations("artifacts");
  const next = theme === "light" ? "dark" : "light";
  const label = t(next === "dark" ? "darkTheme" : "lightTheme");
  const Icon = next === "dark" ? Moon : Sun;
  return (
    <IconButton variant="ghost" aria-label={label} title={label} onClick={() => onChange(next)}>
      <Icon className="h-4 w-4" aria-hidden />
    </IconButton>
  );
}
