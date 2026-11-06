"use client";

import { useTranslations } from "next-intl";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { Checkbox, Input, Label } from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import type { WorkflowCreate } from "@/lib/workflows/types";

type Selection = WorkflowCreate["reply_draft"];

export function ReplyDraftPicker({
  value,
  onChange,
  disabled,
}: {
  value: Selection;
  onChange: (selection: Selection) => void;
  disabled: boolean;
}) {
  const t = useTranslations("workflows.replyDraft");
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={value !== undefined}
          disabled={disabled}
          onCheckedChange={(checked) =>
            onChange(checked === true ? { model_profile_id: "", max_cost_usd: 0.1 } : undefined)
          }
        />
        {t("enable")}
      </label>
      <p className="text-muted-foreground text-xs">{t("description")}</p>
      {value ? (
        <>
          <DraftModelChoice
            value={value.model_profile_id}
            onChange={(model_profile_id) =>
              onChange({ ...value, model_profile_id: model_profile_id ?? "" })
            }
            disabled={disabled}
          />
          <Label htmlFor="reply-draft-budget">{t("budget")}</Label>
          <Input
            id="reply-draft-budget"
            type="number"
            min={0.01}
            max={5}
            step={0.01}
            value={value.max_cost_usd}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, max_cost_usd: Number(event.target.value) })}
          />
        </>
      ) : null}
    </div>
  );
}
function DraftModelChoice({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string | null) => void;
  disabled: boolean;
}) {
  const { profiles, profilesStatus } = useModelProviders();
  return (
    <ModelProfilePicker
      profiles={profiles}
      profilesStatus={profilesStatus}
      value={value || null}
      onChange={onChange}
      allowAdd={false}
      allowRemove={false}
      disabled={disabled}
    />
  );
}
