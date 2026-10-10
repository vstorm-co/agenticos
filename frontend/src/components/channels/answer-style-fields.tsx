"use client";

import { useTranslations } from "next-intl";

import {
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import type { AnswerStyle, ChannelPlatform, StepDisplay } from "@/types/channels";

export const DEFAULT_ANSWER_STYLE: AnswerStyle = {
  ack_reaction: null,
  stream_answers: true,
  step_display: "timeline",
  rate_answers: true,
};

/** An emoji's name as the platforms spell it, without colons - what the server accepts. */
export const REACTION_PATTERN = /^[a-z0-9_+-]{1,64}$/;

/**
 * How a bot answers, beyond what it says (#2084).
 *
 * A reaction on the question the moment it arrives, thumbs under the answer to
 * rate it, and - on Slack, which draws an answer while it is written - whether
 * it streams with a step per tool call, as a timeline or as one plan.
 */
export function AnswerStyleFields({
  idPrefix,
  platform,
  value,
  onChange,
}: {
  idPrefix: string;
  platform: ChannelPlatform;
  value: AnswerStyle;
  onChange: (value: AnswerStyle) => void;
}) {
  const t = useTranslations("pages.channels");
  const reaction = value.ack_reaction ?? "";
  const badReaction = reaction !== "" && !REACTION_PATTERN.test(reaction);

  return (
    <fieldset className="space-y-4 rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">{t("answerStyle")}</legend>
      <FormField
        label={t("ackReaction")}
        htmlFor={`${idPrefix}-ack-reaction`}
        description={platform === "telegram" ? t("ackReactionHintTelegram") : t("ackReactionHint")}
        error={badReaction ? t("ackReactionInvalid") : undefined}
      >
        <Input
          id={`${idPrefix}-ack-reaction`}
          value={reaction}
          // i18n-exempt: an emoji's name, the same in every language
          placeholder="eyes"
          onChange={(event) =>
            onChange({ ...value, ack_reaction: event.target.value.trim().toLowerCase() || null })
          }
          maxLength={64}
          className="max-w-56 font-mono"
        />
      </FormField>

      <div className="flex items-start gap-3">
        <Switch
          id={`${idPrefix}-rate-answers`}
          checked={value.rate_answers}
          onCheckedChange={(checked) => onChange({ ...value, rate_answers: checked })}
        />
        <div className="space-y-0.5">
          <Label htmlFor={`${idPrefix}-rate-answers`}>{t("rateAnswers")}</Label>
          <p className="text-muted-foreground text-xs">{t("rateAnswersHint")}</p>
        </div>
      </div>

      {platform === "slack" && (
        <>
          <div className="flex items-start gap-3">
            <Switch
              id={`${idPrefix}-stream-answers`}
              checked={value.stream_answers}
              onCheckedChange={(checked) => onChange({ ...value, stream_answers: checked })}
            />
            <div className="space-y-0.5">
              <Label htmlFor={`${idPrefix}-stream-answers`}>{t("streamAnswers")}</Label>
              <p className="text-muted-foreground text-xs">{t("streamAnswersHint")}</p>
            </div>
          </div>
          <FormField
            label={t("stepDisplay")}
            htmlFor={`${idPrefix}-step-display`}
            description={t("stepDisplayHint")}
          >
            <Select
              value={value.step_display}
              onValueChange={(next) => onChange({ ...value, step_display: next as StepDisplay })}
              disabled={!value.stream_answers}
            >
              <SelectTrigger id={`${idPrefix}-step-display`} className="max-w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="timeline">{t("stepDisplayTimeline")}</SelectItem>
                <SelectItem value="plan">{t("stepDisplayPlan")}</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
        </>
      )}
    </fieldset>
  );
}
