"use client";

import { useTranslations } from "next-intl";

import { Label, Switch } from "@/components/ui";

/**
 * Whether visitors of a hosted page or a widget may call the agent (#54).
 *
 * Off by default, and separate from dictation: a call is a paid realtime
 * session with the agent, not a way to type. The hint says what a visitor's
 * call leaves out - they cannot approve, so tools that need approval are not
 * in it - and what it counts against.
 *
 * **Offered only where a call would start.** The backend refuses switching it
 * on while the organization's voice switch is off or the agent has no voice to
 * call with, so the switch is locked then with the reason beside it. An embed
 * already on keeps it - a key deleted since must not lock the form - and says
 * visitors see no call button until the agent can take calls again. When the
 * agent's readiness could not be read at all, the switch says so rather than
 * sitting locked with no reason.
 */
export function EmbedVoiceField({
  name,
  value,
  disabled,
  available,
  unchecked,
  wasOn,
  onChange,
}: {
  /** Tells this switch apart from another form's on the same page. */
  name: string;
  value: boolean;
  disabled: boolean;
  /** Whether a call to the agent would start from an embed; null while unknown. */
  available: boolean | null;
  /** The agent's readiness could not be read, so `available` stays null. */
  unchecked: boolean;
  /** Whether the stored embed already has calls on. */
  wasOn: boolean;
  onChange: (on: boolean) => void;
}) {
  const t = useTranslations("agents");
  const locked = disabled || (!wasOn && available !== true);

  return (
    <div className="space-y-1.5">
      <div className="flex items-start gap-3">
        <Switch
          id={name}
          checked={value}
          disabled={locked}
          onCheckedChange={onChange}
          className="mt-0.5"
        />
        <div className="space-y-0.5">
          <Label htmlFor={name}>{t("embedVoice")}</Label>
          <p className="text-muted-foreground text-xs">{t("embedVoiceHint")}</p>
        </div>
      </div>
      {available === false && (
        <p className="text-muted-foreground text-xs">
          {wasOn ? t("embedVoiceDrift") : t("embedVoiceUnavailable")}
        </p>
      )}
      {available === null && unchecked && (
        <p className="text-muted-foreground text-xs">{t("embedVoiceUnchecked")}</p>
      )}
    </div>
  );
}
