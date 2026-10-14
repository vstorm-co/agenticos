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
import {
  choiceOf,
  TranscriptionFields,
  type TranscriptionChoice,
} from "@/components/channels/transcription-fields";
import { useChannelBot } from "@/hooks/use-channel-bots";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { ChannelBot, ChannelBotUpdate, ChannelPlatform } from "@/types/channels";
import { useTranslations } from "next-intl";

const PLATFORM_LABEL: Record<ChannelPlatform, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
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
  transcription: TranscriptionChoice;
}

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
  }

  if (bot.platform === "slack") {
    const signingSecret = draft.signingSecret.trim();
    if (signingSecret) patch.slack_signing_secret = signingSecret;
    const appToken = draft.appToken.trim();
    if (appToken) patch.slack_app_token = appToken;
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
    transcription: choiceOf(bot),
  });
  // The single-bot read carries what "inherit" resolves to; the row the list
  // handed over does not, because resolving it reads the bot's agent.
  const inherited = useChannelBot(bot.id)?.inherited_speech_to_text;
  const [errors, setErrors] = useState<Record<string, string>>({});

  function set<K extends keyof ChannelBotDraft>(field: K, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  /** Whether a credential the dialog cannot read back is already stored. */
  function stored(has: boolean) {
    return has ? t("credentialStored") : t("credentialUnset");
  }

  const patch = botPatch(bot, draft);
  const shortToken = draft.token.trim().length > 0 && draft.token.trim().length < MIN_TOKEN;
  const nothingToSave = Object.keys(patch).length === 0;

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

      <div className="max-h-[65vh] scrollbar-thin space-y-5 overflow-y-auto px-1">
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

        {bot.platform === "slack" && (
          <div className="grid gap-4 sm:grid-cols-2">
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
          </div>
        )}

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
        <Button onClick={submit} disabled={nothingToSave || shortToken || isPending}>
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
