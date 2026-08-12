"use client";

import { useTranslations } from "next-intl";

import { Upload } from "lucide-react";

import {
  Button,
  Checkbox,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  MarkdownEditor,
  SelectValue,
} from "@/components/ui";
import type { EmbedVariable, HostedLogo, PageConfig } from "@/types/embeds";
import { useRef } from "react";

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
  hasCustomLogo,
  onUpload,
  onChange,
}: {
  config: PageConfig;
  variables: EmbedVariable[];
  disabled: boolean;
  /** Whether a picture is already stored for this page. */
  hasCustomLogo: boolean;
  /**
   * Send a file, or `undefined` on a page that does not exist yet.
   *
   * An upload needs a row to attach to, and the row is created by the form this
   * sits in - so a page being published offers the choice and says what it
   * needs, rather than opening a file picker that would have nowhere to put the
   * result.
   */
  onUpload?: (file: File) => void;
  onChange: (config: PageConfig) => void;
}) {
  const t = useTranslations("agents");
  const picker = useRef<HTMLInputElement>(null);
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
        {/* The same editor "Context for this placement" uses, and for a related
            reason: this is Markdown, and three rows of a plain textarea is a
            keyhole onto prose somebody is composing. The difference is who reads
            it - the placement note is read by the model, and this is rendered to
            the visitor - which is why the page renders it as Markdown too rather
            than printing the asterisks. */}
        <MarkdownEditor
          id="hosted-welcome"
          value={config.welcome}
          onChange={(next) => onChange({ ...config, welcome: next.slice(0, MAX_WELCOME) })}
          label={t("hostedWelcome")}
          rows={6}
          disabled={disabled}
        />
        <p className="text-muted-foreground text-xs">{t("hostedWelcomeHint")}</p>
      </div>

      <div className="space-y-2">
        <Label>{t("pageCapabilities")}</Label>
        <Label className="flex items-start gap-2 font-normal">
          <Checkbox
            checked={config.allow_new_conversation}
            disabled={disabled}
            onCheckedChange={(checked) =>
              onChange({ ...config, allow_new_conversation: checked === true })
            }
          />
          <span>
            <span className="text-sm">{t("pageAllowNewConversation")}</span>
            <span className="text-muted-foreground block text-xs">
              {t("pageAllowNewConversationHint")}
            </span>
          </span>
        </Label>
        <Label className="flex items-start gap-2 font-normal">
          <Checkbox
            checked={config.allow_voice}
            disabled={disabled}
            onCheckedChange={(checked) => onChange({ ...config, allow_voice: checked === true })}
          />
          <span>
            <span className="text-sm">{t("pageAllowVoice")}</span>
            <span className="text-muted-foreground block text-xs">{t("pageAllowVoiceHint")}</span>
          </span>
        </Label>
        <Label className="flex items-start gap-2 font-normal">
          <Checkbox
            checked={config.allow_files}
            disabled={disabled}
            onCheckedChange={(checked) => onChange({ ...config, allow_files: checked === true })}
          />
          <span>
            <span className="text-sm">{t("pageAllowFiles")}</span>
            <span className="text-muted-foreground block text-xs">{t("pageAllowFilesHint")}</span>
          </span>
        </Label>
      </div>

      <div className="space-y-2">
        <Label>{t("pageShows")}</Label>
        {/* A filter on what the server *sends*, which is why the hints say
            "sent" rather than "shown": reasoning hidden in CSS is an agent's
            reasoning sitting in a stranger's devtools. */}
        <p className="text-muted-foreground text-xs">{t("pageShowsHint")}</p>
        <Label className="flex items-start gap-2 font-normal">
          <Checkbox
            checked={config.show_tool_steps}
            disabled={disabled}
            onCheckedChange={(checked) =>
              onChange({ ...config, show_tool_steps: checked === true })
            }
          />
          <span>
            <span className="text-sm">{t("pageShowToolSteps")}</span>
            <span className="text-muted-foreground block text-xs">
              {t("pageShowToolStepsHint")}
            </span>
          </span>
        </Label>
        <Label className="flex items-start gap-2 font-normal">
          <Checkbox
            checked={config.show_tool_results}
            // Nothing to open while the steps themselves are not sent, and the
            // server enforces the same thing - a box that could be ticked into
            // having no effect is one somebody would tick.
            disabled={disabled || !config.show_tool_steps}
            onCheckedChange={(checked) =>
              onChange({ ...config, show_tool_results: checked === true })
            }
          />
          <span>
            <span className="text-sm">{t("pageShowToolResults")}</span>
            <span className="text-muted-foreground block text-xs">
              {t("pageShowToolResultsHint")}
            </span>
          </span>
        </Label>
        <Label className="flex items-start gap-2 font-normal">
          <Checkbox
            checked={config.show_thinking}
            disabled={disabled}
            onCheckedChange={(checked) => onChange({ ...config, show_thinking: checked === true })}
          />
          <span>
            <span className="text-sm">{t("pageShowThinking")}</span>
            <span className="text-muted-foreground block text-xs">{t("pageShowThinkingHint")}</span>
          </span>
        </Label>
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
            <SelectItem value="custom" disabled={onUpload === undefined && !hasCustomLogo}>
              {t("hostedLogoCustom")}
            </SelectItem>
            <SelectItem value="none">{t("hostedLogoNone")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("hostedLogoHint")}</p>

        {/* Beside the greyed option rather than under it once chosen: on a page
            that does not exist yet the option cannot be chosen at all, so a
            hint gated on choosing it is one nobody can read. */}
        {onUpload === undefined && (
          <p className="text-muted-foreground text-xs">{t("hostedLogoPublishFirst")}</p>
        )}

        {config.logo === "custom" && onUpload !== undefined && (
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={picker}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onUpload(file);
                // Cleared so choosing the same file twice fires again, which
                // is what somebody does after a refused upload.
                event.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => picker.current?.click()}
            >
              <Upload className="h-3.5 w-3.5" />
              {hasCustomLogo ? t("hostedLogoReplace") : t("hostedLogoUpload")}
            </Button>
            <span className="text-muted-foreground text-xs">{t("hostedLogoLimits")}</span>
          </div>
        )}
      </div>
    </div>
  );
}
