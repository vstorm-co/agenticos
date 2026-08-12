"use client";

import { useTranslations } from "next-intl";

import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import type { EmbedVariable, HostedLogo, PageConfig } from "@/types/embeds";

const MAX_TITLE = 80;
const MAX_WELCOME = 600;

/**
 * What a page we serve ourselves looks like.
 *
 * The shortest integration this product has: send somebody a link. Four fields,
 * all optional, and none of them shared with a widget - a launcher label and a
 * corner to sit in mean nothing on a full page, and a page needs a browser-tab
 * title a bubble has no use for.
 *
 * The one refusal it has to surface before the save is a *required* variable
 * that is not URL-safe: a page's own URL is the only source of a value there, so
 * that combination is a promise the surface structurally cannot keep. The
 * backend refuses it with a message; showing the reason here is what stops
 * somebody meeting it.
 */
export function PageFields({
  config,
  variables,
  disabled,
  onChange,
}: {
  config: PageConfig;
  variables: EmbedVariable[];
  disabled: boolean;
  onChange: (config: PageConfig) => void;
}) {
  const t = useTranslations("agents");
  const unreachable = variables
    .filter((variable) => variable.required && !variable.url_safe && variable.name.trim() !== "")
    .map((variable) => variable.name);

  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-xs">{t("hostedLinkProtection")}</p>

      {unreachable.length > 0 && (
        <p className="text-destructive text-xs">
          {t("hostedRequiredNotUrlSafe", { names: unreachable.join(", ") })}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="hosted-title">{t("hostedTitle")}</Label>
          <Input
            id="hosted-title"
            value={config.title}
            maxLength={MAX_TITLE}
            disabled={disabled}
            onChange={(event) => onChange({ ...config, title: event.target.value })}
          />
          <p className="text-muted-foreground text-xs">{t("hostedTitleHint")}</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="hosted-accent">{t("hostedAccent")}</Label>
          <div className="flex items-center gap-2">
            <input
              id="hosted-accent"
              type="color"
              value={config.accent}
              disabled={disabled}
              onChange={(event) => onChange({ ...config, accent: event.target.value })}
              className="border-input h-9 w-12 cursor-pointer rounded-md border bg-transparent"
            />
            <Input
              value={config.accent}
              disabled={disabled}
              onChange={(event) => onChange({ ...config, accent: event.target.value })}
              className="font-mono"
              aria-label={t("hostedAccent")}
            />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="hosted-welcome">{t("hostedWelcome")}</Label>
        <Textarea
          id="hosted-welcome"
          value={config.welcome}
          rows={3}
          maxLength={MAX_WELCOME}
          disabled={disabled}
          onChange={(event) => onChange({ ...config, welcome: event.target.value })}
        />
        <p className="text-muted-foreground text-xs">{t("hostedWelcomeHint")}</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="hosted-logo">{t("hostedLogo")}</Label>
        <Select
          value={config.logo}
          onValueChange={(value) => onChange({ ...config, logo: value as HostedLogo })}
        >
          <SelectTrigger id="hosted-logo">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="agent">{t("hostedLogoAgent")}</SelectItem>
            <SelectItem value="organization">{t("hostedLogoOrganization")}</SelectItem>
            <SelectItem value="none">{t("hostedLogoNone")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("hostedLogoHint")}</p>
      </div>
    </div>
  );
}
