"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
} from "@/components/ui";
import { submitFailure } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import type { ChannelBotCreate, ChannelPlatform } from "@/types/channels";
import { useTranslations } from "next-intl";

const PLATFORMS: readonly ChannelPlatform[] = ["mattermost", "slack", "telegram"];

const PLATFORM_LABEL: Record<ChannelPlatform, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
};

/** Where each platform's token comes from - the one thing people get stuck on. */
const TOKEN_HINT: Record<ChannelPlatform, string> = {
  telegram: "botTokenHintTelegram",
  slack: "botTokenHintSlack",
  mattermost: "botTokenHintMattermost",
};

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 255;
const MAX_URL = 500;
const MIN_TOKEN = 10;

interface AddChannelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (bot: ChannelBotCreate) => Promise<unknown>;
  isPending: boolean;
}

/**
 * Register one chat platform for the organization.
 *
 * A dialog rather than a form stapled under the list, which is what this was:
 * six inputs sat permanently below the rows, two of them appearing and
 * disappearing as the platform changed, so the page was mostly a form about a
 * thing you do once and mostly a list of things you look at every day.
 *
 * The platform is asked first because it decides the rest - Mattermost is
 * self-hosted and cannot answer without its server's address, Slack is its own
 * app and carries its own signing secret - and asking for those fields
 * unconditionally is asking three quarters of people to skip two inputs.
 *
 * Every credential here is write-only: sent once, sealed at rest, never read
 * back. The same bargain as the Vault.
 */
export function AddChannelDialog({
  open,
  onOpenChange,
  onSubmit,
  isPending,
}: AddChannelDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  const [platform, setPlatform] = useState<ChannelPlatform>("mattermost");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [signingSecret, setSigningSecret] = useState("");
  const [appToken, setAppToken] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Mattermost is self-hosted: without its server's address a bot cannot reply,
  // cannot open its event stream and cannot fetch an attachment, so the backend
  // refuses to save one. Said here rather than after the round trip.
  const missingServerUrl = platform === "mattermost" && serverUrl.trim() === "";
  const complete = name.trim().length > 0 && token.trim().length >= MIN_TOKEN && !missingServerUrl;

  function reset() {
    setPlatform("mattermost");
    setName("");
    setToken("");
    setServerUrl("");
    setWebhookSecret("");
    setSigningSecret("");
    setAppToken("");
    setErrors({});
  }

  /** Another platform asks other questions, so the answers to the old ones go. */
  function choosePlatform(next: ChannelPlatform) {
    setPlatform(next);
    setServerUrl("");
    setWebhookSecret("");
    setSigningSecret("");
    setAppToken("");
    setErrors({});
  }

  async function submit() {
    try {
      await onSubmit({
        platform,
        name: name.trim(),
        token: token.trim(),
        // Absent rather than empty, like the token itself: the backend applies
        // what it was sent, and a blank string is a value.
        ...(platform === "mattermost" && serverUrl.trim()
          ? { api_base_url: serverUrl.trim() }
          : {}),
        ...(platform === "mattermost" && webhookSecret.trim()
          ? { webhook_secret: webhookSecret.trim() }
          : {}),
        ...(platform === "slack" && signingSecret.trim()
          ? { slack_signing_secret: signingSecret.trim() }
          : {}),
        ...(platform === "slack" && appToken.trim() ? { slack_app_token: appToken.trim() } : {}),
      });
      onOpenChange(false);
      reset();
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: ["name", "token", "api_base_url", "webhook_secret"],
          identifiedBy: "name",
        },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("addChannel")}</DialogTitle>
          <DialogDescription>{t("addChannelDescription")}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[65vh] space-y-5 overflow-y-auto px-1">
          {/* A caption over a group of buttons, not a `Label`: a label names one
              control and this one names three. */}
          <div className="space-y-2">
            <p id="channel-platform" className="text-sm leading-none font-medium">
              {t("platform")}
            </p>
            <div role="group" aria-labelledby="channel-platform" className="grid grid-cols-3 gap-2">
              {PLATFORMS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => choosePlatform(option)}
                  aria-pressed={platform === option}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
                    platform === option
                      ? "border-brand bg-brand/5 text-foreground"
                      : "border-input hover:bg-accent/50 text-muted-foreground",
                  )}
                >
                  <ChannelPlatformIcon platform={option} />
                  <span className="font-medium">{PLATFORM_LABEL[option]}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("name")}
              htmlFor="channel-name"
              error={errors.name}
              description={t("nameHint")}
              required
            >
              <Input
                id="channel-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("supportBot")}
                maxLength={MAX_NAME}
              />
            </FormField>

            <FormField
              label={t("botToken")}
              htmlFor="channel-token"
              error={errors.token}
              description={t(TOKEN_HINT[platform])}
              required
            >
              <Input
                id="channel-token"
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                autoComplete="off"
              />
            </FormField>
          </div>

          {platform === "mattermost" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                label={t("mattermostServerUrl")}
                htmlFor="channel-server-url"
                error={errors.api_base_url}
                description={t("mattermostServerUrlHint")}
                required
              >
                <Input
                  id="channel-server-url"
                  value={serverUrl}
                  onChange={(event) => setServerUrl(event.target.value)}
                  placeholder="https://mattermost.example.com"
                  maxLength={MAX_URL}
                />
              </FormField>

              <FormField
                label={t("mattermostWebhookToken")}
                htmlFor="channel-webhook-secret"
                error={errors.webhook_secret}
                description={t("mattermostWebhookTokenHint")}
              >
                <Input
                  id="channel-webhook-secret"
                  type="password"
                  value={webhookSecret}
                  onChange={(event) => setWebhookSecret(event.target.value)}
                  autoComplete="off"
                  maxLength={MAX_NAME}
                />
              </FormField>
            </div>
          )}

          {platform === "slack" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                label={t("signingSecret")}
                htmlFor="channel-signing-secret"
                description={t("signingSecretHint")}
              >
                <Input
                  id="channel-signing-secret"
                  type="password"
                  value={signingSecret}
                  onChange={(event) => setSigningSecret(event.target.value)}
                  autoComplete="off"
                />
              </FormField>

              <FormField
                label={t("appLevelToken")}
                htmlFor="channel-app-token"
                description={t("appLevelTokenHint")}
              >
                <Input
                  id="channel-app-token"
                  type="password"
                  value={appToken}
                  onChange={(event) => setAppToken(event.target.value)}
                  autoComplete="off"
                />
              </FormField>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={submit} disabled={!complete || isPending}>
            {t("register")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
