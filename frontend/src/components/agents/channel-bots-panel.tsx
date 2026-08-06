"use client";

import { useState } from "react";
import { Pause, Play, Plus, Trash2 } from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useChannelBots } from "@/hooks";
import type { ChannelBot, ChannelPlatform } from "@/types/channels";
import { useTranslations } from "next-intl";

const PLATFORM_LABEL: Record<ChannelPlatform, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
};

/** What to paste, per platform - the one thing people get stuck on. */
/** Catalog key per platform; the sentence is in `messages/en.json`. */
const TOKEN_HINT: Record<ChannelPlatform, string> = {
  telegram: "botTokenHintTelegram",
  slack: "botTokenHintSlack",
  mattermost: "botTokenHintMattermost",
};

/**
 * The organization's channel bots - the other half of the Builder's "where is
 * this agent available" section, which can only bind to bots registered here.
 *
 * It renders in the Builder rather than with the organization settings so the
 * register-then-bind flow is one screen, but a bot stays an organization
 * resource: one bot serves many agents, and this same list appears in every
 * agent's Availability tab.
 *
 * The token is write-only: sent once at registration, encrypted at rest, never
 * read back - the same bargain as the Vault.
 */
export function ChannelBotsPanel({ canManage }: { canManage: boolean }) {
  const t = useTranslations("agents");
  const { bots, isLoading, create, setActive, setUsageReporting, remove } =
    useChannelBots(canManage);
  const [platform, setPlatform] = useState<ChannelPlatform>("telegram");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [signingSecret, setSigningSecret] = useState("");
  const [appToken, setAppToken] = useState("");

  if (!canManage) return null;

  async function register() {
    await create.mutateAsync({
      platform,
      name: name.trim(),
      token: token.trim(),
      // Slack only: each bot is its own Slack app and carries its own
      // credentials. Absent rather than empty, like the token itself.
      ...(platform === "slack" && signingSecret.trim()
        ? { slack_signing_secret: signingSecret.trim() }
        : {}),
      ...(platform === "slack" && appToken.trim() ? { slack_app_token: appToken.trim() } : {}),
    });
    setName("");
    setToken("");
    setSigningSecret("");
    setAppToken("");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("channelBots")}</CardTitle>
        <CardDescription>{t("botConnectsOrganizationChat")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!isLoading && bots.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("noBotsYetRegister")}</p>
        )}

        {bots.map((bot) => (
          <div key={bot.id} className="flex items-center gap-3 rounded-md border p-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm">
                {PLATFORM_LABEL[bot.platform] ?? bot.platform} - {bot.name}
              </p>
              <p className="text-muted-foreground text-xs">
                {bot.webhook_mode ? t("webhook") : t("polling")}
              </p>
            </div>
            {bot.platform === "slack" && !bot.has_slack_signing_secret && (
              // Without it, inbound events cannot be verified and the webhook
              // refuses everything - worth a badge before anyone debugs a
              // silent bot.
              <Badge variant="secondary">{t("noSigningSecret")}</Badge>
            )}
            {!bot.is_active && <Badge variant="secondary">{t("inactive")}</Badge>}
            {/* How talkative this bot is about what a turn cost. A bot that stops
                answering because the organization hit its cap looks broken, and
                the difference between "broken" and "out of budget" is somebody
                having said so beforehand. */}
            <Select
              value={bot.usage_reporting.mode}
              // Not `!canManage ||`: the panel renders nothing at all for
              // somebody who may not manage bots, so that half could never be
              // false here.
              disabled={setUsageReporting.isPending}
              onValueChange={(mode) =>
                setUsageReporting.mutate({
                  botId: bot.id,
                  usageReporting: {
                    ...bot.usage_reporting,
                    mode: mode as ChannelBot["usage_reporting"]["mode"],
                  },
                })
              }
            >
              <SelectTrigger className="w-44" aria-label={`Usage reporting on ${bot.name}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="off">{t("usageLogOnly")}</SelectItem>
                <SelectItem value="near_limit">{t("usageNearLimit")}</SelectItem>
                <SelectItem value="every_n">
                  {t("usageEveryNMessages", { count: bot.usage_reporting.every_n })}
                </SelectItem>
                <SelectItem value="always">{t("usageEveryReply")}</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="sm"
              disabled={setActive.isPending}
              aria-label={bot.is_active ? `Deactivate ${bot.name}` : `Activate ${bot.name}`}
              onClick={() => setActive.mutate({ botId: bot.id, isActive: !bot.is_active })}
            >
              {bot.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={remove.isPending}
              aria-label={`Remove ${bot.name}`}
              onClick={() => remove.mutate(bot.id)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}

        <div className="grid items-end gap-3 border-t pt-3 sm:grid-cols-[10rem_1fr_1fr_auto]">
          <div className="space-y-1">
            <Label htmlFor="bot-platform">{t("platform")}</Label>
            <Select
              value={platform}
              onValueChange={(value) => setPlatform(value as ChannelPlatform)}
            >
              <SelectTrigger id="bot-platform">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(PLATFORM_LABEL) as ChannelPlatform[]).map((key) => (
                  <SelectItem key={key} value={key}>
                    {PLATFORM_LABEL[key]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="bot-name">{t("name3")}</Label>
            <Input
              id="bot-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("supportBot")}
              maxLength={255}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="bot-token">{t("botToken")}</Label>
            <Input
              id="bot-token"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={t(TOKEN_HINT[platform])}
            />
          </div>
          <Button
            onClick={register}
            disabled={!name.trim() || token.trim().length < 10 || create.isPending}
          >
            <Plus className="h-4 w-4" />
            {t("register")}
          </Button>
        </div>

        {platform === "slack" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="bot-signing-secret">{t("signingSecret")}</Label>
              <Input
                id="bot-signing-secret"
                type="password"
                value={signingSecret}
                onChange={(event) => setSigningSecret(event.target.value)}
                placeholder={t("basicInformationAppCredentials")}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="bot-app-token">{t("appLevelTokenOptional")}</Label>
              <Input
                id="bot-app-token"
                type="password"
                value={appToken}
                onChange={(event) => setAppToken(event.target.value)}
                placeholder={t("xappSocketModeDev")}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
