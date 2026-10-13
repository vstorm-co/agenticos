"use client";

import { useTranslations } from "next-intl";

import {
  FormField,
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
 * The reactions offered, by the name the platforms take and the emoji it
 * draws. The set Telegram allows a bot, which Slack and Mattermost both know
 * too - so one list is right on every platform, and nobody has to remember
 * that it is `eyes` and not `:eyes:`.
 */
export const REACTIONS: readonly (readonly [name: string, emoji: string])[] = [
  ["eyes", "👀"],
  ["+1", "👍"],
  ["ok_hand", "👌"],
  ["fire", "🔥"],
  ["thinking_face", "🤔"],
  ["writing_hand", "✍️"],
  ["zap", "⚡"],
  ["hourglass", "⌛"],
];

/** The select's value for "no reaction" - a name no platform spells. */
const NONE = "none";

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
  const reaction = value.ack_reaction;
  // A reaction stored before this list existed is still offered, so opening
  // the form never silently changes it.
  const options =
    reaction !== null && !REACTIONS.some(([name]) => name === reaction)
      ? [...REACTIONS, [reaction, ""] as const]
      : REACTIONS;

  return (
    <div className="space-y-4">
      <p className="text-sm font-medium">{t("answerStyle")}</p>
      <FormField
        label={t("ackReaction")}
        htmlFor={`${idPrefix}-ack-reaction`}
        description={t("ackReactionHint")}
      >
        <Select
          value={reaction ?? NONE}
          onValueChange={(next) =>
            onChange({ ...value, ack_reaction: next === NONE ? null : next })
          }
        >
          <SelectTrigger id={`${idPrefix}-ack-reaction`} className="max-w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>{t("noReaction")}</SelectItem>
            {options.map(([name, emoji]) => (
              <SelectItem key={name} value={name} textValue={name}>
                {/* i18n-exempt: an emoji and its platform name, the same in every language */}
                <span className="flex items-center gap-2">
                  <span aria-hidden className="w-5 text-center text-base leading-none">
                    {emoji}
                  </span>
                  <span className="font-mono text-xs">{name}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
    </div>
  );
}
