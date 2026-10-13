"use client";

import { Globe, MicOff, Server, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { EmbedDictation } from "@/types/embeds";

const MODES: { value: EmbedDictation; icon: LucideIcon; label: string; hint: string }[] = [
  { value: "off", icon: MicOff, label: "embedDictationOff", hint: "embedDictationOffHint" },
  {
    value: "browser",
    icon: Globe,
    label: "embedDictationBrowser",
    hint: "embedDictationBrowserHint",
  },
  {
    value: "server",
    icon: Server,
    label: "embedDictationServer",
    hint: "embedDictationServerHint",
  },
];

/**
 * How a visitor dictates on a hosted page or in a widget: off, the browser's
 * recogniser, or the organization's own speech-to-text provider.
 *
 * Each choice says where the audio goes, because that is the decision being
 * made: `browser` hands a stranger's voice to the browser's vendor, `server`
 * sends it to the organization's provider and its bill.
 *
 * **Server is offered only where it would be accepted.** The backend refuses
 * switching it on while no provider and credential resolve for the agent, so
 * the choice is disabled then with the reason beside it. A page already on
 * `server` keeps it selectable - a key deleted since must not lock the form -
 * and says that visitors see no microphone until a provider answers again.
 *
 * Native radios inside labels, like the organization's Voice card: there is no
 * radio-group primitive in `ui/`.
 */
export function EmbedDictationField({
  name,
  value,
  disabled,
  serverAvailable,
  wasServer,
  onChange,
}: {
  /** Tells this group's radios apart from another form's on the same page. */
  name: string;
  value: EmbedDictation;
  disabled: boolean;
  /** Whether a provider and credential resolve for the agent; null while unknown. */
  serverAvailable: boolean | null;
  /** Whether the stored embed is already on `server`. */
  wasServer: boolean;
  onChange: (value: EmbedDictation) => void;
}) {
  const t = useTranslations("agents");
  const serverLocked = !wasServer && serverAvailable !== true;

  return (
    <fieldset role="radiogroup" aria-label={t("embedDictation")} className="space-y-2">
      <legend className="text-sm leading-none font-medium">{t("embedDictation")}</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        {MODES.map(({ value: mode, icon: Icon, label, hint }) => {
          const locked = disabled || (mode === "server" && serverLocked);
          return (
            <label
              key={mode}
              className={cn(
                "border-border bg-card focus-within:ring-ring relative grid cursor-pointer grid-cols-[auto_1fr] gap-x-2.5 gap-y-0.5 rounded-xl border p-3 transition-colors focus-within:ring-2",
                "has-[:checked]:border-foreground has-[:checked]:bg-muted",
                locked && "cursor-not-allowed opacity-55",
              )}
            >
              <input
                type="radio"
                name={name}
                value={mode}
                checked={value === mode}
                disabled={locked}
                onChange={() => onChange(mode)}
                className="pointer-events-none absolute opacity-0"
              />
              <Icon className="text-muted-foreground mt-0.5 h-4 w-4" aria-hidden />
              <span className="text-sm font-semibold">{t(label)}</span>
              <span className="text-muted-foreground col-start-2 text-xs">{t(hint)}</span>
            </label>
          );
        })}
      </div>
      {serverAvailable === false && (
        <p className="text-muted-foreground text-xs">
          {wasServer ? t("embedDictationServerDrift") : t("embedDictationServerUnavailable")}
        </p>
      )}
    </fieldset>
  );
}
