"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { Monitor, Moon, Sun } from "lucide-react";
import { LookPicker } from "@/components/settings/look-picker";
import { ChoiceGroup } from "@/components/ui/choice-group";
import { useMounted } from "@/hooks/use-mounted";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import { useThemeStore, type Theme } from "@/stores/theme-store";
import styles from "./start-preferences.module.css";

/** The same deliberate setters that AppearanceSettings synchronizes through the account. */
export function StartPreferencesAppearance() {
  const t = useTranslations("appearance");
  const themeCopy = useTranslations("theme");
  const mounted = useMounted();
  const { theme, setTheme, look, setLook } = useThemeStore();
  const resolved = useResolvedTheme();
  const lookId = useId();
  const themeId = useId();
  return (
    <div className={styles.appearance}>
      <div className={styles.theme}>
        <p id={themeId} className={styles.label}>
          {t("theme")}
        </p>
        <ChoiceGroup<Theme>
          labelledBy={themeId}
          value={mounted ? theme : undefined}
          options={[
            { value: "light", label: themeCopy("light"), icon: Sun },
            { value: "dark", label: themeCopy("dark"), icon: Moon },
            { value: "system", label: themeCopy("system"), icon: Monitor },
          ]}
          onChange={setTheme}
        />
      </div>
      <div className={styles.looks}>
        <p id={lookId} className={styles.label}>
          {t("look")}
        </p>
        <LookPicker
          labelledBy={lookId}
          value={mounted ? look : undefined}
          dark={resolved === "dark"}
          onChange={setLook}
        />
      </div>
    </div>
  );
}
