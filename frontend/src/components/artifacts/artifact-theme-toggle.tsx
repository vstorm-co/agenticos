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
  return (
    <div role="group" aria-label={t("appTheme")} className="flex shrink-0 items-center gap-1">
      <IconButton
        variant={theme === "light" ? "secondary" : "ghost"}
        aria-label={t("lightTheme")}
        title={t("lightTheme")}
        aria-pressed={theme === "light"}
        onClick={() => onChange("light")}
      >
        <Sun className="h-4 w-4" aria-hidden />
      </IconButton>
      <IconButton
        variant={theme === "dark" ? "secondary" : "ghost"}
        aria-label={t("darkTheme")}
        title={t("darkTheme")}
        aria-pressed={theme === "dark"}
        onClick={() => onChange("dark")}
      >
        <Moon className="h-4 w-4" aria-hidden />
      </IconButton>
    </div>
  );
}
