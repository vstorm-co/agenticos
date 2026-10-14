"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { toast } from "sonner";

import { Button, Checkbox, Input, Label, Switch } from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useOrganizations, usePermissions } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { useVoiceUsage } from "@/hooks/use-voice-usage";
import { NO_FAILURE, submitFailure, type SubmitFailure } from "@/lib/api-error";
import type { Organization, VoiceConversationsUpdate } from "@/types";
import { Perm } from "@/types/permissions";

/** The fields a refusal can name, so each message lands under its control. */
const FIELDS = [
  "voice_conversations_enabled",
  "voice_in_chat",
  "voice_max_call_seconds",
  "voice_monthly_minutes",
] as const;

const MAX_MINUTES = 50;

/** This calendar month so far, in UTC like the limit: the window the line reports on. */
function thisMonth(now: Date = new Date()): { start: string; end: string } {
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  return { start: start.toISOString(), end: now.toISOString() };
}

interface Draft {
  enabled: boolean;
  inChat: boolean;
  /** The longest call as typed, in whole minutes. */
  maxMinutes: string;
  /** The monthly minutes as typed; ignored while `unlimited`. */
  monthly: string;
  unlimited: boolean;
}

function draftOf(org: Organization): Draft {
  return {
    enabled: org.voice_conversations_enabled,
    inChat: org.voice_in_chat,
    maxMinutes: String(Math.round(org.voice_max_call_seconds / 60)),
    monthly: org.voice_monthly_minutes === null ? "" : String(org.voice_monthly_minutes),
    unlimited: org.voice_monthly_minutes === null,
  };
}

/** A whole number from `low` up to `high`, or `null`. */
function wholeIn(text: string, low: number, high: number): number | null {
  const value = Number(text.trim());
  return text.trim() !== "" && Number.isInteger(value) && value >= low && value <= high
    ? value
    : null;
}

/**
 * What Save would send, by value rather than by keystroke: a monthly figure
 * typed and then dropped for "no monthly limit" is no change at all. The
 * minutes only for a `budgets:manage` holder; a value the server would refuse
 * is named instead.
 */
function changes(
  draft: Draft,
  stored: Draft,
  org: Organization,
  mayBudget: boolean,
): { update: VoiceConversationsUpdate; problem: "max" | "monthly" | null } {
  const update: VoiceConversationsUpdate = {};
  if (draft.enabled !== stored.enabled) update.voice_conversations_enabled = draft.enabled;
  if (draft.inChat !== stored.inChat) update.voice_in_chat = draft.inChat;
  if (draft.maxMinutes !== stored.maxMinutes) {
    const minutes = wholeIn(draft.maxMinutes, 1, MAX_MINUTES);
    if (minutes === null) return { update, problem: "max" };
    update.voice_max_call_seconds = minutes * 60;
  }
  if (mayBudget) {
    const minutes = draft.unlimited ? null : wholeIn(draft.monthly, 1, Number.MAX_SAFE_INTEGER);
    if (!draft.unlimited && minutes === null) return { update, problem: "monthly" };
    if (minutes !== org.voice_monthly_minutes) update.voice_monthly_minutes = minutes;
  }
  return { update, problem: null };
}

/**
 * The section's draft, and saving it: only what changed is sent, and the
 * monthly minutes only by somebody holding `budgets:manage` - the server
 * refuses the whole PATCH otherwise.
 */
function useConversationsDraft(org: Organization, mayBudget: boolean) {
  const t = useTranslations("teams.voice.conversations");
  const tErrors = useTranslations("errors");
  const { setVoiceConversations } = useOrganizations();
  const stored = draftOf(org);
  const [draft, setDraft] = useState(stored);
  const [failure, setFailure] = useState<SubmitFailure>(NO_FAILURE);
  const [invalid, setInvalid] = useState<"max" | "monthly" | null>(null);
  const [saving, setSaving] = useState(false);

  // Re-seed when the stored settings change underneath, during render.
  if (useChanged(`${org.id}|${JSON.stringify(stored)}`)) setDraft(stored);

  const edit = (next: Partial<Draft>) => {
    setDraft((prev) => ({ ...prev, ...next }));
    setFailure(NO_FAILURE);
    setInvalid(null);
  };

  const save = async () => {
    const { update, problem } = changes(draft, stored, org, mayBudget);
    if (problem !== null) return setInvalid(problem);
    setSaving(true);
    try {
      await setVoiceConversations(org.id, update);
      toast.success(t("saved"));
    } catch (error) {
      const problem = submitFailure(error, { fields: FIELDS }, tErrors);
      setFailure(problem);
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setDraft(stored);
    setFailure(NO_FAILURE);
    setInvalid(null);
  };

  // Dirty only when Save would send something, or has something to refuse:
  // edits that cancel out leave nothing to save.
  const pending = changes(draft, stored, org, mayBudget);
  const dirty = Object.keys(pending.update).length > 0 || pending.problem !== null;
  return { draft, edit, save, reset, dirty, failure, invalid, saving };
}

/**
 * The organization's voice-call settings (#54), inside the Voice card where
 * "coming soon" stood: whether members may call agents at all, whether `/chat`
 * offers it, the longest call, and the monthly minutes - a spend limit, so
 * editable only with `budgets:manage` and read-only otherwise.
 */
export function OrgVoiceConversations({ org }: { org: Organization }) {
  const t = useTranslations("teams.voice");
  const { can } = usePermissions();
  const mayBudget = can(Perm.budgetsManage);
  const form = useConversationsDraft(org, mayBudget);
  const { draft, failure } = form;
  const maxError =
    form.invalid === "max"
      ? t("conversations.maxInvalid")
      : (failure.fields.voice_max_call_seconds ?? null);

  return (
    <section
      id="org-voice-conversations"
      data-tour="org-voice-conversations"
      className="border-border mt-6 border-t pt-5"
    >
      <h3 className="text-sm font-semibold">{t("conversationsTitle")}</h3>
      <p className="text-muted-foreground mt-0.5 mb-4 text-sm">{t("conversationsDescription")}</p>
      <div className="space-y-4">
        <ToggleRow
          label={t("conversations.enabled")}
          hint={t("conversations.enabledHint")}
          checked={draft.enabled}
          error={failure.fields.voice_conversations_enabled}
          onChange={(enabled) => form.edit({ enabled })}
        />
        <ToggleRow
          label={t("conversations.inChat")}
          hint={t("conversations.inChatHint")}
          checked={draft.inChat}
          disabled={!draft.enabled}
          error={failure.fields.voice_in_chat}
          onChange={(inChat) => form.edit({ inChat })}
        />
        <FormField
          htmlFor="org-voice-call-max"
          label={t("conversations.maxLength")}
          description={t("conversations.maxHint")}
          error={maxError}
        >
          <Input
            inputMode="numeric"
            className="w-24"
            value={draft.maxMinutes}
            onChange={(event) => form.edit({ maxMinutes: event.target.value })}
          />
        </FormField>
        {mayBudget ? (
          <MonthlyField
            draft={draft}
            error={
              form.invalid === "monthly"
                ? t("conversations.monthlyInvalid")
                : (failure.fields.voice_monthly_minutes ?? null)
            }
            onChange={form.edit}
          />
        ) : (
          <p className="text-sm">
            {org.voice_monthly_minutes === null
              ? t("conversations.monthlyUnlimited")
              : t("conversations.monthlyReadOnly", { minutes: org.voice_monthly_minutes })}
          </p>
        )}
        <MonthUsed limit={org.voice_monthly_minutes} />
        <p className="text-muted-foreground text-xs">{t("conversations.budgetsNote")}</p>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={!form.dirty || form.saving}
          onClick={form.reset}
        >
          {t("cancel")}
        </Button>
        <Button size="sm" disabled={!form.dirty || form.saving} onClick={() => void form.save()}>
          {form.saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          {t("save")}
        </Button>
      </div>
    </section>
  );
}

/**
 * This month's call minutes against the limit, for a `runs:view` holder only:
 * the read names agents and refuses anyone else, so nothing is asked for them.
 * Hidden while loading and on a failure - an outage is not "0 minutes used".
 */
function MonthUsed({ limit }: { limit: number | null }) {
  const t = useTranslations("teams.voice.conversations");
  const { can } = usePermissions();
  // Fixed at mount: "now" moving on every render would be a new query each time.
  const [range] = useState(thisMonth);
  const { usage } = useVoiceUsage(range, { enabled: can(Perm.runsView) });
  if (usage === null) return null;
  const used = Math.round(usage.month_seconds / 60);
  return (
    <p className="text-sm">
      {limit === null ? t("usedNoLimit", { used }) : t("used", { used, limit })}
    </p>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  disabled,
  error,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  error: string | undefined;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-0.5">
        <Label htmlFor={id}>{label}</Label>
        <p className={error ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
          {error ?? hint}
        </p>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  );
}

function MonthlyField({
  draft,
  error,
  onChange,
}: {
  draft: Draft;
  error: string | null;
  onChange: (next: Partial<Draft>) => void;
}) {
  const t = useTranslations("teams.voice.conversations");
  return (
    <div className="space-y-2">
      <FormField
        htmlFor="org-voice-call-monthly"
        label={t("monthly")}
        description={t("monthlyHint")}
        error={error}
      >
        <Input
          inputMode="numeric"
          className="w-28"
          value={draft.monthly}
          disabled={draft.unlimited}
          onChange={(event) => onChange({ monthly: event.target.value })}
        />
      </FormField>
      <div className="flex items-center gap-2">
        <Checkbox
          id="org-voice-call-unlimited"
          checked={draft.unlimited}
          onCheckedChange={(checked) => onChange({ unlimited: checked === true })}
        />
        <Label htmlFor="org-voice-call-unlimited" className="font-normal">
          {t("monthlyNone")}
        </Label>
      </div>
    </div>
  );
}
