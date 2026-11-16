"use client";

import { useState } from "react";
import { Check } from "lucide-react";
import { toast } from "sonner";

import {
  AnswerStyleFields,
  defaultAnswerStyle,
  REACTION_PATTERN,
} from "@/components/channels/answer-style-fields";
import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import { SlackTransport } from "@/components/channels/slack-transport";
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
  MoreOptions,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  INHERIT,
  TranscriptionFields,
  type TranscriptionChoice,
} from "@/components/channels/transcription-fields";
import { useOrganizationList } from "@/hooks";
import { useOrgStore } from "@/stores";
import { submitFailure } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import type {
  AnswerStyle,
  ChannelBotCreate,
  ChannelPlatform,
  InheritedSpeechToText,
} from "@/types/channels";
import { MentionPolicyFields } from "./mention-policy-fields";
import { DiscordGuildsField, parseDiscordGuilds, validDiscordGuilds } from "./discord-guilds-field";
import { useTranslations } from "next-intl";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";

const PLATFORMS: readonly ChannelPlatform[] = [
  "discord",
  "mattermost",
  "slack",
  "teams",
  "telegram",
  "sms",
  "email",
  "imessage",
];

const PLATFORM_LABEL: Record<ChannelPlatform, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
  // i18n-exempt: a product\'s own name, written the same in every language
  teams: "Microsoft Teams",
  // i18n-exempt: Twilio is the provider's own name
  sms: "SMS (Twilio)",
  // i18n-exempt: the name of the protocol, written the same in every language
  email: "Email",
  imessage: "iMessage",

  discord: "Discord",
};

/** Where each platform's token comes from - the one thing people get stuck on. */
const TOKEN_HINT: Record<ChannelPlatform, string> = {
  telegram: "botTokenHintTelegram",
  slack: "botTokenHintSlack",
  mattermost: "botTokenHintMattermost",
  teams: "botTokenHintTeams",
  sms: "botTokenHintSms",
  email: "botTokenHintEmail",
  imessage: "botTokenHintImessage",

  discord: "botTokenHintDiscord",
};

/** The shortest secret the backend accepts for a relay to sign with. */
const MIN_RELAY_SECRET = 8;

/** A long random string, so nobody has to invent one. */
function generateRelaySecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** An Entra app or tenant id - what the backend accepts for either. */
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 255;
const MAX_URL = 500;
const MIN_TOKEN = 10;

interface AddChannelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (bot: ChannelBotCreate) => Promise<unknown>;
  isPending: boolean;
  /** The platform picked first - the Builder opens this from a platform's tile. */
  initialPlatform?: ChannelPlatform;
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
  initialPlatform = "mattermost",
}: AddChannelDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  const [platform, setPlatform] = useState<ChannelPlatform>(initialPlatform);
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [signingSecret, setSigningSecret] = useState("");
  const [appToken, setAppToken] = useState("");
  const [slackWebhook, setSlackWebhook] = useState(true);
  const [teamsAppId, setTeamsAppId] = useState("");
  const [teamsTenantId, setTeamsTenantId] = useState("");
  const [respondToBroadcasts, setRespondToBroadcasts] = useState(false);
  const [discordGuilds, setDiscordGuilds] = useState("");
  const [answerStyle, setAnswerStyle] = useState<AnswerStyle>(() =>
    defaultAnswerStyle(initialPlatform),
  );
  const [transcription, setTranscription] = useState<TranscriptionChoice>(INHERIT);
  // A bot not yet registered serves no agent, so what it would inherit today is
  // the organization's pair; binding an agent with its own may change that.
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const org = orgs?.find((candidate) => candidate.id === activeOrgId);
  const inherited: InheritedSpeechToText | null | undefined =
    org === undefined
      ? undefined
      : org.speech_to_text_provider && org.speech_to_text_model
        ? {
            provider: org.speech_to_text_provider,
            model: org.speech_to_text_model,
            language: org.speech_to_text_language,
            pair_source: "organization",
            language_source: org.speech_to_text_language ? "organization" : null,
            agent_name: null,
            has_key: org.speech_to_text_secret_id !== null,
          }
        : null;
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Mattermost is self-hosted: without its server's address a bot cannot reply,
  // cannot open its event stream and cannot fetch an attachment, so the backend
  // refuses to save one. Said here rather than after the round trip.
  const missingServerUrl =
    (platform === "mattermost" || platform === "imessage") && serverUrl.trim() === "";
  // A Teams bot cannot sign in, nor recognise a token meant for it, without both.
  const missingTeamsIds =
    platform === "teams" && !(GUID.test(teamsAppId.trim()) && GUID.test(teamsTenantId.trim()));
  const badReaction =
    answerStyle.ack_reaction !== null && !REACTION_PATTERN.test(answerStyle.ack_reaction);
  const missingRelaySecret = platform === "email" && webhookSecret.trim().length < MIN_RELAY_SECRET;
  const complete =
    name.trim().length > 0 &&
    token.trim().length >= MIN_TOKEN &&
    !missingServerUrl &&
    !missingTeamsIds &&
    !missingRelaySecret &&
    !badReaction &&
    (platform !== "discord" || validDiscordGuilds(discordGuilds));

  function reset() {
    setPlatform(initialPlatform);
    setName("");
    setToken("");
    setServerUrl("");
    setWebhookSecret("");
    setSigningSecret("");
    setAppToken("");
    setSlackWebhook(true);
    setTeamsAppId("");
    setTeamsTenantId("");
    setAnswerStyle(defaultAnswerStyle(initialPlatform));
    setRespondToBroadcasts(false);
    setDiscordGuilds("");
    setTranscription(INHERIT);
    setErrors({});
  }

  /** Another platform asks other questions, so the answers to the old ones go. */
  function choosePlatform(next: ChannelPlatform) {
    if (next !== platform) setToken("");
    setPlatform(next);
    setDiscordGuilds("");
    setServerUrl("");
    setWebhookSecret("");
    setSigningSecret("");
    setAppToken("");
    setTeamsAppId("");
    setTeamsTenantId("");
    setAnswerStyle((style) => ({ ...style, ack_reaction: defaultAnswerStyle(next).ack_reaction }));
    setErrors({});
  }

  function changeOpen(next: boolean) {
    if (isPending) return;
    if (!next) reset();
    onOpenChange(next);
  }

  async function submit() {
    if (isPending) return;
    try {
      await onSubmit({
        platform,
        name: name.trim(),
        token: token.trim(),
        // Absent rather than empty, like the token itself: the backend applies
        // what it was sent, and a blank string is a value.
        ...((platform === "mattermost" || platform === "imessage") && serverUrl.trim()
          ? { api_base_url: serverUrl.trim() }
          : {}),
        ...((platform === "mattermost" || platform === "email") && webhookSecret.trim()
          ? { webhook_secret: webhookSecret.trim() }
          : {}),
        // Only the credential the chosen direction uses: Slack calling us is
        // verified with the signing secret, us connecting out uses the app token.
        ...(platform === "slack" ? { webhook_mode: slackWebhook } : {}),
        // A text arrives by webhook only: there is no connection to open.
        ...(platform === "sms" || platform === "email" || platform === "imessage"
          ? { webhook_mode: true }
          : {}),
        ...(platform === "slack" && slackWebhook && signingSecret.trim()
          ? { slack_signing_secret: signingSecret.trim() }
          : {}),
        ...(platform === "slack" && !slackWebhook && appToken.trim()
          ? { slack_app_token: appToken.trim() }
          : {}),
        ...(platform === "teams"
          ? { teams_app_id: teamsAppId.trim(), teams_tenant_id: teamsTenantId.trim() }
          : {}),
        ...answerStyle,
        ...(platform === "discord" || respondToBroadcasts
          ? {
              access_policy: {
                ...(respondToBroadcasts ? { respond_to_broadcasts: true } : {}),
                ...(platform === "discord"
                  ? { discord_guild_ids: parseDiscordGuilds(discordGuilds) }
                  : {}),
              },
            }
          : {}),
        // Inherit is the server's default, so it sends nothing; off is the
        // switch; choose is both halves and the key - the schema refuses one
        // half alone as a setting that cannot run, and a pair with no key.
        ...(transcription.mode === "off" ? { transcribe_voice_notes: false } : {}),
        ...(transcription.mode === "choose" && transcription.provider && transcription.model
          ? {
              speech_to_text_provider: transcription.provider,
              speech_to_text_model: transcription.model,
              speech_to_text_secret_id: transcription.secretId,
            }
          : {}),
      });
      onOpenChange(false);
      reset();
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: [
            "name",
            "token",
            "api_base_url",
            "webhook_secret",
            "speech_to_text_secret_id",
            "teams_app_id",
            "teams_tenant_id",
          ],
          identifiedBy: "name",
        },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      {/* One column that scrolls as a whole: the platform, what it needs to
          connect, and the rest folded under More options. */}
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)} dismissible={!isPending}>
        <DialogHeader>
          <DialogTitle>{t("addChannel")}</DialogTitle>
          <DialogDescription>{t("addChannelDescription")}</DialogDescription>
        </DialogHeader>

        <div className={DIALOG_BODY}>
          <fieldset disabled={isPending} className="min-w-0 space-y-5">
            <legend className="sr-only">{t("addChannel")}</legend>
            {/* A caption over a group of buttons, not a `Label`: a label names one
              control and this one names a set of platforms. */}
            <div className="space-y-2">
              <p id="channel-platform" className="text-muted-foreground text-xs font-medium">
                {t("platform")}
              </p>
              <div className="md:hidden">
                <Select
                  value={platform}
                  disabled={isPending}
                  onValueChange={(value) => {
                    const next = PLATFORMS.find((option) => option === value);
                    if (next) choosePlatform(next);
                  }}
                >
                  <SelectTrigger aria-labelledby="channel-platform">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PLATFORMS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {PLATFORM_LABEL[option]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div
                role="group"
                aria-labelledby="channel-platform"
                className="hidden grid-cols-4 gap-2 md:grid"
              >
                {PLATFORMS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => choosePlatform(option)}
                    aria-pressed={platform === option}
                    className={cn(
                      "focus-visible:ring-ring flex min-h-14 min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[13px] transition-colors outline-none focus-visible:ring-2",
                      platform === option
                        ? "border-foreground/35 bg-accent text-foreground"
                        : "bg-background/70 text-muted-foreground hover:border-border hover:text-foreground hover:bg-accent/60 border-transparent",
                    )}
                  >
                    <ChannelPlatformIcon
                      platform={option}
                      className="h-6 w-6 rounded-none bg-transparent"
                    />
                    <span className="min-w-0 flex-1 font-medium">{PLATFORM_LABEL[option]}</span>
                    <Check
                      className={cn("size-3.5 shrink-0", platform !== option && "invisible")}
                      aria-hidden
                    />
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-5">
              <FormField
                label={t("name")}
                htmlFor="channel-name"
                error={errors.name}
                description={t("nameHint")}
                required
              >
                <Input
                  id="channel-name"
                  name="channel_name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t("supportBot")}
                  autoComplete="off"
                  maxLength={MAX_NAME}
                />
              </FormField>

              <FormField
                label={t(platform === "email" ? "emailAddress" : "botToken")}
                htmlFor="channel-token"
                error={errors.token}
                description={t(TOKEN_HINT[platform])}
                required
              >
                <Input
                  key={platform}
                  id="channel-token"
                  name="channel_credential"
                  type={platform === "email" ? "email" : "password"}
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  autoComplete={platform === "email" ? "off" : "new-password"}
                />
              </FormField>
            </div>

            {platform === "discord" && (
              <DiscordGuildsField
                idPrefix="channel"
                value={discordGuilds}
                onChange={setDiscordGuilds}
              />
            )}
            {platform === "mattermost" && (
              <div className="space-y-5">
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

            {platform === "imessage" && (
              <FormField
                label={t("imessageServerUrl")}
                htmlFor="imessage-server-url"
                description={t("imessageServerUrlHint")}
                error={errors.api_base_url}
                required
              >
                <Input
                  id="imessage-server-url"
                  value={serverUrl}
                  onChange={(event) => setServerUrl(event.target.value)}
                  maxLength={MAX_URL}
                  placeholder="http://mac-bridge:1234"
                />
              </FormField>
            )}

            {platform === "email" && (
              <FormField
                label={t("emailRelaySecret")}
                htmlFor="channel-relay-secret"
                error={errors.webhook_secret}
                description={t("emailRelaySecretHint")}
                required
              >
                <div className="flex gap-2">
                  <Input
                    id="channel-relay-secret"
                    type="password"
                    value={webhookSecret}
                    onChange={(event) => setWebhookSecret(event.target.value)}
                    autoComplete="off"
                    maxLength={MAX_NAME}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setWebhookSecret(generateRelaySecret())}
                  >
                    {t("emailGenerateSecret")}
                  </Button>
                </div>
              </FormField>
            )}

            {platform === "teams" && (
              <div className="space-y-5">
                <FormField
                  label={t("teamsAppId")}
                  htmlFor="channel-teams-app-id"
                  error={errors.teams_app_id}
                  description={t("teamsAppIdHint")}
                  required
                >
                  <Input
                    id="channel-teams-app-id"
                    value={teamsAppId}
                    onChange={(event) => setTeamsAppId(event.target.value)}
                    placeholder="00000000-0000-0000-0000-000000000000"
                    autoComplete="off"
                  />
                </FormField>
                <FormField
                  label={t("teamsTenantId")}
                  htmlFor="channel-teams-tenant-id"
                  error={errors.teams_tenant_id}
                  description={t("teamsTenantIdHint")}
                  required
                >
                  <Input
                    id="channel-teams-tenant-id"
                    value={teamsTenantId}
                    onChange={(event) => setTeamsTenantId(event.target.value)}
                    placeholder="00000000-0000-0000-0000-000000000000"
                    autoComplete="off"
                  />
                </FormField>
              </div>
            )}

            {platform === "slack" && (
              <>
                <SlackTransport webhookMode={slackWebhook} onChange={setSlackWebhook} />
                {slackWebhook ? (
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
                ) : (
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
                )}
              </>
            )}

            <MentionPolicyFields
              idPrefix="channel"
              platform={platform}
              enabled={respondToBroadcasts}
              onChange={setRespondToBroadcasts}
            />
            <MoreOptions label={t("moreOptions")}>
              <AnswerStyleFields
                idPrefix="channel"
                platform={platform}
                value={answerStyle}
                onChange={setAnswerStyle}
              />
              <TranscriptionFields
                idPrefix="channel"
                platform={platform}
                inherited={inherited}
                value={transcription}
                onChange={setTranscription}
                keyError={errors.speech_to_text_secret_id}
              />
            </MoreOptions>
          </fieldset>
        </div>

        <DialogFooter>
          <Button variant="outline" disabled={isPending} onClick={() => changeOpen(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={submit} loading={isPending} disabled={!complete}>
            {t("register")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
