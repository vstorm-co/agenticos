"use client";

import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import type { EmbedVariable, HostedConfig, HostedLogo } from "@/types/embeds";
import { useTranslations } from "next-intl";

const MAX_TITLE = 80;
const MAX_WELCOME = 600;

/**
 * Also serve this embed as a page of ours, and what that page looks like.
 *
 * The shortest integration this product has: send somebody a link. It is the
 * same embed underneath - same key, same rate bucket, budget and pause switch -
 * so this is a switch and four fields rather than a second object to configure.
 *
 * Two things it refuses, and it says so before the save rather than after: token
 * auth cannot be hosted, because the token would have to travel in the URL and so
 * into history, referrers and every chat client the link is pasted into; and a
 * *required* variable that is not URL-safe cannot, because a page of ours has no
 * other source for one. The backend refuses both with a message; showing the
 * reason here is what stops somebody meeting it.
 */
export function HostedPageFields({
  hosted,
  config,
  authMode,
  variables,
  disabled,
  onHostedChange,
  onConfigChange,
}: {
  hosted: boolean;
  config: HostedConfig;
  authMode: string;
  variables: EmbedVariable[];
  disabled: boolean;
  onHostedChange: (hosted: boolean) => void;
  onConfigChange: (config: HostedConfig) => void;
}) {
  const t = useTranslations("agents");
  const blockedByAuth = authMode !== "public";
  const unreachable = variables
    .filter((variable) => variable.required && !variable.url_safe && variable.name.trim() !== "")
    .map((variable) => variable.name);

  return (
    <div className="border-border space-y-3 rounded-lg border p-3">
      <Label className="flex items-center gap-2 font-normal">
        <Switch
          checked={hosted && !blockedByAuth}
          disabled={disabled || blockedByAuth}
          onCheckedChange={onHostedChange}
        />
        {t("hostAPage")}
      </Label>
      <p className="text-muted-foreground text-xs">
        {blockedByAuth ? t("hostedNeedsPublicAuth") : t("hostAPageHint")}
      </p>

      {hosted && !blockedByAuth && (
        <>
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
                onChange={(event) => onConfigChange({ ...config, title: event.target.value })}
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
                  onChange={(event) => onConfigChange({ ...config, accent: event.target.value })}
                  className="border-input h-9 w-12 cursor-pointer rounded-md border bg-transparent"
                />
                <Input
                  value={config.accent}
                  disabled={disabled}
                  onChange={(event) => onConfigChange({ ...config, accent: event.target.value })}
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
              onChange={(event) => onConfigChange({ ...config, welcome: event.target.value })}
            />
            <p className="text-muted-foreground text-xs">{t("hostedWelcomeHint")}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="hosted-logo">{t("hostedLogo")}</Label>
            <Select
              value={config.logo}
              onValueChange={(value) => onConfigChange({ ...config, logo: value as HostedLogo })}
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
        </>
      )}
    </div>
  );
}
