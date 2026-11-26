import { isLook } from "./appearance";
import { useThemeStore, type Theme } from "@/stores/theme-store";

/** Only the platform's own successful preference result may dress this console. */
export function appearanceChosenBy(toolName: string, result: string): void {
  if (toolName !== "agenticos_set_my_preferences") return;
  let value: unknown;
  try {
    value = JSON.parse(result);
  } catch {
    return;
  }
  if (!value || typeof value !== "object" || !("theme" in value) || !("look" in value)) return;
  const theme: Theme | null =
    value.theme === "light" || value.theme === "dark" || value.theme === "system"
      ? value.theme
      : null;
  const look = isLook(value.look) ? value.look : null;
  useThemeStore.setState({
    ...(theme === null ? {} : { theme }),
    ...(look === null ? {} : { look }),
  });
}
