"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useThemeStore, Theme, getResolvedTheme } from "@/stores/theme-store";
import { useTranslations } from "next-intl";

interface ThemeToggleProps {
  variant?: "icon" | "dropdown";
  className?: string;
}

export function ThemeToggle({ variant = "icon", className }: ThemeToggleProps) {
  const t = useTranslations("theme");
  const { theme, setTheme } = useThemeStore();
  // `false` on the server, `true` once hydrated - which is the whole question,
  // and `useSyncExternalStore` answers it without a state write in an effect.
  // The subscribe callback never fires: the value cannot change after mount.
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

  const resolvedTheme = getResolvedTheme(theme);

  const cycleTheme = () => {
    const themes: Theme[] = ["light", "dark", "system"];
    const currentIndex = themes.indexOf(theme ?? "system");
    const nextIndex = (currentIndex + 1) % themes.length;
    setTheme(themes[nextIndex] ?? "system");
  };

  // Render placeholder during SSR to prevent hydration mismatch
  if (!mounted) {
    return (
      <Button variant="ghost" size="icon" className={className} aria-label={t("toggleTheme")}>
        <Sun className="h-5 w-5" />
      </Button>
    );
  }

  if (variant === "icon") {
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={cycleTheme}
        className={className}
        aria-label={t("switchThemeCurrent", { theme })}
        title={`Theme: ${theme}`}
      >
        {resolvedTheme === "dark" ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}
        {theme === "system" && <span className="sr-only">{t("followingSystem")}</span>}
      </Button>
    );
  }

  return (
    <div className={`flex gap-1 ${className}`}>
      <Button
        variant={theme === "light" ? "default" : "ghost"}
        size="icon"
        onClick={() => setTheme("light")}
        aria-label={t("lightMode")}
        title={t("lightMode2")}
      >
        <Sun className="h-4 w-4" />
      </Button>
      <Button
        variant={theme === "dark" ? "default" : "ghost"}
        size="icon"
        onClick={() => setTheme("dark")}
        aria-label={t("darkMode")}
        title={t("darkMode2")}
      >
        <Moon className="h-4 w-4" />
      </Button>
      <Button
        variant={theme === "system" ? "default" : "ghost"}
        size="icon"
        onClick={() => setTheme("system")}
        aria-label={t("systemTheme")}
        title={t("systemTheme2")}
      >
        <Monitor className="h-4 w-4" />
      </Button>
    </div>
  );
}
