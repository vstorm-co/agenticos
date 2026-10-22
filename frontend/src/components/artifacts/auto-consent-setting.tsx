"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ConfirmDialog, Label, Switch } from "@/components/ui";
import type { ArtifactConsent } from "@/types/artifact";

/**
 * The version of the text a person agrees to by turning auto-consent on. The
 * server accepts only the one it knows and records it in the audit entry, so a
 * change to `autoConsentConfirm`'s meaning goes with a new value on both sides.
 */
export const AUTO_CONSENT_WORDING = "auto_consent.v1";

interface AutoConsentSettingProps {
  consent: ArtifactConsent;
  /**
   * Sends the change; `confirmed` names the text agreed to when turning it on.
   * `onDone` runs once the server took it - a refusal is the caller's to report.
   */
  onChange: (changes: { enabled: boolean; confirmed?: string }, onDone?: () => void) => void;
  saving: boolean;
}

/**
 * "Don't ask for consent on republish", in the Share dialog of a page that reads
 * data. Only the page's owner turns it on - through a popup saying what it does -
 * and the owner or an Owner or Admin turns it off, at once. Rendered only for a
 * caller who may change it one way or the other; the switch is held in the
 * direction they may not move it.
 */
export function AutoConsentSetting({ consent, onChange, saving }: AutoConsentSettingProps) {
  const t = useTranslations("artifacts.consent");
  const [asking, setAsking] = useState(false);
  if (!consent.may_enable_auto_consent && !consent.may_disable_auto_consent) return null;
  const movable = consent.auto_consent
    ? consent.may_disable_auto_consent
    : consent.may_enable_auto_consent;
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border p-3">
      <div className="space-y-1">
        <Label htmlFor="artifact-auto-consent">{t("autoConsent")}</Label>
        <p className="text-muted-foreground text-sm">{t("autoConsentWhy")}</p>
      </div>
      <Switch
        id="artifact-auto-consent"
        checked={consent.auto_consent}
        disabled={!movable || saving}
        onCheckedChange={(next) => {
          if (next) setAsking(true);
          else onChange({ enabled: false });
        }}
      />
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("autoConsentConfirmTitle")}
        description={t("autoConsentConfirm")}
        confirmLabel={t("autoConsentTurnOn")}
        loading={saving}
        onConfirm={() =>
          onChange({ enabled: true, confirmed: AUTO_CONSENT_WORDING }, () => setAsking(false))
        }
      />
    </div>
  );
}
