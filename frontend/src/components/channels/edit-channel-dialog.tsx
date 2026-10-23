"use client";

import { useState } from "react";
import { ClipboardCopy, Download } from "lucide-react";
import { toast } from "sonner";

import { AnswerStyleFields, REACTION_PATTERN } from "@/components/channels/answer-style-fields";
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
} from "@/components/ui";
import {
  choiceOf,
  TranscriptionFields,
  type TranscriptionChoice,
} from "@/components/channels/transcription-fields";
import {
  useChannelBot,
  useCopySlackManifest,
  useDownloadTeamsPackage,
} from "@/hooks/use-channel-bots";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL_GUTTER } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { AnswerStyle, ChannelBot, ChannelBotUpdate, ChannelPlatform } from "@/types/channels";
import { useTranslations } from "next-intl";

const PLATFORM_LABEL: Record<ChannelPlatform, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
  // i18n-exempt: a product\'s own name, written the same in every language
  teams: "Microsoft Teams",
};

const MAX_NAME = 255;
const MAX_URL = 500;
const MIN_TOKEN = 10;

/** What somebody typed into the dialog, before it becomes a patch. */
export interface ChannelBotDraft {
  name: string;
  token: string;
  serverUrl: string;
  webhookSecret: string;
  signingSecret: string;
  appToken: string;
  commandToken: string;
  /** Slack: whether Slack calls this deployment, or the deployment connects out. */
  webhookMode: boolean;
  answerStyle: AnswerStyle;
  transcription: TranscriptionChoice;
}

const ANSWER_STYLE_FIELDS = [
  "ack_reaction",
  "stream_answers",
  "step_display",
  "rate_answers",
] as const;

/**
 * The fields that actually changed, as the PATCH body.
 *
 * Two rules, and both matter more than they look. A **credential is sent only
 * when somebody typed one**, because the backend reads an omitted field as
 * "keep the stored value" and a blank string as a value - so submitting every
 * input would wipe every credential the operator did not retype. And a **field
 * equal to what is already stored is not sent**, so saving a dialog nobody
 * edited is a no-op rather than a write that reseals the same token under a new
 * key version.
 */
export function botPatch(bot: ChannelBot, draft: ChannelBotDraft): ChannelBotUpdate {
  const patch: ChannelBotUpdate = {};
  const name = draft.name.trim();
  if (name && name !== bot.name) patch.name = name;

  const token = draft.token.trim();
  if (token) patch.token = token;

  if (bot.platform === "mattermost") {
    const serverUrl = draft.serverUrl.trim();
    if (serverUrl && serverUrl !== bot.api_base_url) patch.api_base_url = serverUrl;
    const webhookSecret = draft.webhookSecret.trim();
    if (webhookSecret) patch.webhook_secret = webhookSecret;
    const commandToken = draft.commandToken.trim();
    if (commandToken) patch.command_token = commandToken;
  }

  if (bot.platform === "slack") {
    const signingSecret = draft.signingSecret.trim();
    if (signingSecret) patch.slack_signing_secret = signingSecret;
    const appToken = draft.appToken.trim();
    if (appToken) patch.slack_app_token = appToken;
    if (draft.webhookMode !== bot.webhook_mode) patch.webhook_mode = draft.webhookMode;
  }

  for (const field of ANSWER_STYLE_FIELDS) {
    if (draft.answerStyle[field] !== bot[field]) {
      Object.assign(patch, { [field]: draft.answerStyle[field] });
    }
  }

  Object.assign(patch, transcriptionPatch(bot, draft.transcription));
  return patch;
}

/**
 * The transcription half of the patch: the switch, and the pair with its key,
 * each only where it moved.
 *
 * Off is the switch alone - the server clears the pair and the key with it.
 * Inherit is the switch back on where it was off, and a null pair where the
 * bot had its own; a null pair no longer means off (#1797), and the server
 * clears the key with it. Choose is the switch on and both halves and the key
 * whenever any of them moved, because the server checks them together against
 * the stored row: a provider alone would be refused as a setting that cannot
 * run, and a new provider without its key as a pair with nothing to pay with.
 */
function transcriptionPatch(bot: ChannelBot, choice: TranscriptionChoice): ChannelBotUpdate {
  if (choice.mode === "off") {
    return bot.transcribe_voice_notes ? { transcribe_voice_notes: false } : {};
  }
  const patch: ChannelBotUpdate = bot.transcribe_voice_notes
    ? {}
    : { transcribe_voice_notes: true };
  const { provider, model, secretId } = choice;
  if (
    provider !== bot.speech_to_text_provider ||
    model !== bot.speech_to_text_model ||
    (choice.mode === "choose" && secretId !== bot.speech_to_text_secret_id)
  ) {
    patch.speech_to_text_provider = provider;
    patch.speech_to_text_model = model;
    if (choice.mode === "choose") patch.speech_to_text_secret_id = secretId;
  }
  return patch;
}

interface BotEditFormProps {
  bot: ChannelBot;
  onOpenChange: (open: boolean) => void;
  onSubmit: (botId: string, data: ChannelBotUpdate) => Promise<unknown>;
  isPending: boolean;
}

/**
 * The inputs, mounted per bot.
 *
 * Its own component so the draft can be initialised from `bot` at mount and
 * reset by remounting - the parent keys it on the bot's id. The alternative is
 * an effect that calls `setDraft` when `bot` changes, which is a cascading
 * render and which the lint rule for it is right about: there is no external
 * system to synchronise with here, only state that belongs to one row.
 *
 * Credentials start empty on every open because none of them is readable, and
 * the caption under each says whether one is stored.
 */
function BotEditForm({ bot, onOpenChange, onSubmit, isPending }: BotEditFormProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  const [draft, setDraft] = useState<ChannelBotDraft>({
    name: bot.name,
    token: "",
    serverUrl: bot.api_base_url ?? "",
    webhookSecret: "",
    signingSecret: "",
    appToken: "",
    commandToken: "",
    webhookMode: bot.webhook_mode,
    answerStyle: {
      ack_reaction: bot.ack_reaction,
      stream_answers: bot.stream_answers,
      step_display: bot.step_display,
      rate_answers: bot.rate_answers,
    },
    transcription: choiceOf(bot),
  });
  // The single-bot read carries what "inherit" resolves to; the row the list
  // handed over does not, because resolving it reads the bot's agent.
  const inherited = useChannelBot(bot.id)?.inherited_speech_to_text;
  const [errors, setErrors] = useState<Record<string, string>>({});

  function set(
    field:
      | "name"
      | "token"
      | "serverUrl"
      | "webhookSecret"
      | "signingSecret"
      | "appToken"
      | "commandToken",
    value: string,
  ) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  /** Whether a credential the dialog cannot read back is already stored. */
  function stored(has: boolean) {
    return has ? t("credentialStored") : t("credentialUnset");
  }

  const patch = botPatch(bot, draft);
  const shortToken = draft.token.trim().length > 0 && draft.token.trim().length < MIN_TOKEN;
  const nothingToSave = Object.keys(patch).length === 0;
  const badReaction =
    draft.answerStyle.ack_reaction !== null &&
    !REACTION_PATTERN.test(draft.answerStyle.ack_reaction);

  async function submit() {
    try {
      await onSubmit(bot.id, patch);
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: [
            "name",
            "token",
            "api_base_url",
            "webhook_secret",
            "transcribe_voice_notes",
            "speech_to_text_secret_id",
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
    <>
      <DialogHeader>
        <DialogTitle>{t("editChannel")}</DialogTitle>
        <DialogDescription>{t("editChannelDescription")}</DialogDescription>
      </DialogHeader>

      <div className={cn("max-h-[65vh] space-y-5 overflow-y-auto pl-1", DIALOG_SCROLL_GUTTER)}>
        <div className="text-muted-foreground flex items-center gap-2.5 text-sm">
          <ChannelPlatformIcon platform={bot.platform} />
          <span>{PLATFORM_LABEL[bot.platform]}</span>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            label={t("name")}
            htmlFor="edit-channel-name"
            error={errors.name}
            description={t("nameHint")}
            required
          >
            <Input
              id="edit-channel-name"
              value={draft.name}
              onChange={(event) => set("name", event.target.value)}
              maxLength={MAX_NAME}
            />
          </FormField>

          <FormField
            label={t("replaceBotToken")}
            htmlFor="edit-channel-token"
            error={errors.token ?? (shortToken ? t("tokenTooShort") : undefined)}
            description={t("credentialStored")}
          >
            <Input
              id="edit-channel-token"
              type="password"
              value={draft.token}
              onChange={(event) => set("token", event.target.value)}
              autoComplete="off"
            />
          </FormField>
        </div>

        {bot.platform === "mattermost" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("mattermostServerUrl")}
              htmlFor="edit-channel-server-url"
              error={errors.api_base_url}
              description={t("mattermostServerUrlHint")}
              required
            >
              <Input
                id="edit-channel-server-url"
                value={draft.serverUrl}
                onChange={(event) => set("serverUrl", event.target.value)}
                maxLength={MAX_URL}
              />
            </FormField>

            <FormField
              label={t("mattermostWebhookToken")}
              htmlFor="edit-channel-webhook-secret"
              error={errors.webhook_secret}
              description={stored(bot.has_webhook_secret)}
            >
              <Input
                id="edit-channel-webhook-secret"
                type="password"
                value={draft.webhookSecret}
                onChange={(event) => set("webhookSecret", event.target.value)}
                autoComplete="off"
                maxLength={MAX_NAME}
              />
            </FormField>
          </div>
        )}

        {bot.platform === "mattermost" && bot.command_url && (
          <MattermostCommand
            url={bot.command_url}
            token={draft.commandToken}
            stored={stored(bot.has_command_token)}
            onToken={(value) => set("commandToken", value)}
          />
        )}

        {bot.platform === "slack" && (
          <SlackTransport
            webhookMode={draft.webhookMode}
            onChange={(webhookMode) => setDraft((current) => ({ ...current, webhookMode }))}
          />
        )}

        {bot.platform === "slack" && <SlackManifest botId={bot.id} />}

        {bot.platform === "teams" && <TeamsSetup bot={bot} />}

        {bot.platform === "slack" &&
          (draft.webhookMode ? (
            <FormField
              label={t("signingSecret")}
              htmlFor="edit-channel-signing-secret"
              description={stored(bot.has_slack_signing_secret)}
            >
              <Input
                id="edit-channel-signing-secret"
                type="password"
                value={draft.signingSecret}
                onChange={(event) => set("signingSecret", event.target.value)}
                autoComplete="off"
              />
            </FormField>
          ) : (
            <FormField
              label={t("appLevelToken")}
              htmlFor="edit-channel-app-token"
              description={stored(bot.has_slack_app_token)}
            >
              <Input
                id="edit-channel-app-token"
                type="password"
                value={draft.appToken}
                onChange={(event) => set("appToken", event.target.value)}
                autoComplete="off"
              />
            </FormField>
          ))}

        <AnswerStyleFields
          idPrefix="edit-channel"
          platform={bot.platform}
          value={draft.answerStyle}
          onChange={(answerStyle) => setDraft((current) => ({ ...current, answerStyle }))}
        />

        <TranscriptionFields
          idPrefix="edit-channel"
          platform={bot.platform}
          inherited={inherited}
          value={draft.transcription}
          onChange={(transcription) => setDraft((current) => ({ ...current, transcription }))}
          keyError={errors.speech_to_text_secret_id}
        />
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          {t("cancel")}
        </Button>
        <Button onClick={submit} disabled={nothingToSave || shortToken || badReaction || isPending}>
          {t("save")}
        </Button>
      </DialogFooter>
    </>
  );
}

interface EditChannelDialogProps {
  /** The bot being edited; `null` closes the dialog. */
  bot: ChannelBot | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (botId: string, data: ChannelBotUpdate) => Promise<unknown>;
  isPending: boolean;
}

/**
 * Change a bot's name, or replace one of its credentials.
 *
 * This exists because a Slack app issues its credentials from three different
 * screens: the `xoxb-` bot token at install, the signing secret under Basic
 * Information, and the `xapp-` App-Level Token from a fourth place again -
 * generated, in practice, minutes after the bot was registered here. Without a
 * way back in, supplying the one the transport needs meant deleting the bot,
 * which takes its agent binding with it.
 *
 * The platform is shown and not offered: it decides which credentials the row
 * carries and how inbound messages reach it, so changing it is registering a
 * different bot rather than editing this one.
 *
 * Nor is the transport offered. Switching a bot to webhook mode is only half a
 * move - the webhook has to be registered with the platform, which is what
 * mints the secret Telegram is handed - and a toggle here would leave a bot
 * reporting `webhook` and answering nothing. `channel-webhook-register` does
 * both halves.
 */
export function EditChannelDialog({
  bot,
  onOpenChange,
  onSubmit,
  isPending,
}: EditChannelDialogProps) {
  return (
    <Dialog open={bot !== null} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        {bot && (
          <BotEditForm
            key={bot.id}
            bot={bot}
            onOpenChange={onOpenChange}
            onSubmit={onSubmit}
            isPending={isPending}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * The Slack app, set up in one paste (#2067): the manifest names every URL Slack
 * calls, so the administrator creates the app from it instead of copying them.
 */
function SlackManifest({ botId }: { botId: string }) {
  const t = useTranslations("pages.channels");
  const copy = useCopySlackManifest();
  return (
    <div className="border-border flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center">
      <p className="text-muted-foreground flex-1 text-sm">{t("slackManifestWhy")}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => copy.mutate(botId)}
        disabled={copy.isPending}
      >
        <ClipboardCopy className="h-4 w-4" />
        {t("slackManifestCopy")}
      </Button>
    </div>
  );
}

/**
 * A Teams bot, set up in two steps (#1985): its messaging endpoint goes into the
 * Azure Bot resource, and the app package into the tenant's app catalog.
 */
function TeamsSetup({ bot }: { bot: ChannelBot }) {
  const t = useTranslations("pages.channels");
  const download = useDownloadTeamsPackage();
  return (
    <div className="border-border space-y-3 rounded-lg border p-3">
      {bot.messaging_endpoint && (
        <div className="space-y-1">
          <p className="text-sm font-medium">{t("teamsEndpoint")}</p>
          <p className="text-muted-foreground text-xs">{t("teamsEndpointHint")}</p>
          <code className="bg-muted block rounded-md px-2 py-1.5 text-xs break-all">
            {bot.messaging_endpoint}
          </code>
        </div>
      )}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <p className="text-muted-foreground flex-1 text-sm">{t("teamsPackageWhy")}</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => download.mutate({ id: bot.id, name: bot.name })}
          disabled={download.isPending}
        >
          <Download className="h-4 w-4" />
          {t("teamsPackageDownload")}
        </Button>
      </div>
    </div>
  );
}

/**
 * Mattermost's `/agent` (#2084): the request URL to paste into the slash command
 * Mattermost creates, and the token it hands back, which every request carries.
 */
function MattermostCommand({
  url,
  token,
  stored,
  onToken,
}: {
  url: string;
  token: string;
  stored: string;
  onToken: (value: string) => void;
}) {
  const t = useTranslations("pages.channels");
  return (
    <div className="space-y-3 rounded-lg border p-3">
      <p className="text-muted-foreground text-sm">{t("mattermostCommandWhy")}</p>
      <div className="flex items-center gap-2">
        <code className="bg-muted min-w-0 flex-1 truncate rounded px-2 py-1 text-xs">{url}</code>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={async () => {
            await navigator.clipboard.writeText(url);
            toast.success(t("mattermostCommandUrlCopied"));
          }}
        >
          <ClipboardCopy className="h-4 w-4" />
          {t("mattermostCommandUrlCopy")}
        </Button>
      </div>
      <FormField
        label={t("mattermostCommandToken")}
        htmlFor="edit-channel-command-token"
        description={stored}
      >
        <Input
          id="edit-channel-command-token"
          type="password"
          value={token}
          onChange={(event) => onToken(event.target.value)}
          autoComplete="off"
          maxLength={255}
        />
      </FormField>
    </div>
  );
}
