"use client";

import { DatasetIcon } from "./dataset-chip";
import { Sparkles, TrendingUp } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { PipelineModelPicker } from "@/components/evals/pipeline-model-picker";
import {
  Button,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  MarkdownEditor,
} from "@/components/ui";
import { useDataset } from "@/hooks/use-datasets";
import { useModelProviders } from "@/hooks/use-model-providers";
import { MoreOptions } from "@/components/ui/more-options";
import { usePermissions } from "@/hooks/use-permissions";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { getErrorMessage } from "@/lib/api-error";
import type { Dataset, DatasetHelperSettings } from "@/types/datasets";
import { Perm } from "@/types/permissions";

const EMPTY: DatasetHelperSettings = {
  generator: { model_profile_id: null, instructions: null },
  improver: { model_profile_id: null, instructions: null },
};

/** Dataset-owned pipeline settings, using the same model and instruction controls as Build. */
export function HelperSettings({
  dataset,
  kind,
}: {
  dataset: Dataset;
  kind: keyof DatasetHelperSettings;
}) {
  const t = useTranslations("datasets.helpers");
  const tc = useTranslations("common");
  const ta = useTranslations("pages.agents");
  const tErrors = useTranslations("errors");
  const stored = dataset.helper_settings ?? EMPTY;
  const [draft, setDraft] = useState(stored[kind]);
  const [base, setBase] = useState(stored[kind]);
  if (JSON.stringify(base) !== JSON.stringify(stored[kind])) {
    setBase(stored[kind]);
    if (JSON.stringify(draft) === JSON.stringify(base)) setDraft(stored[kind]);
  }
  const { update } = useDataset(dataset.id);
  const { profiles, profilesStatus } = useModelProviders();
  const { can } = usePermissions();
  const Icon = kind === "generator" ? Sparkles : TrendingUp;
  const dirty = JSON.stringify(draft) !== JSON.stringify(stored[kind]);
  const disabled = !dataset.can_edit || update.isPending;
  async function save() {
    try {
      const updated = await update.mutateAsync({ helper_settings: { [kind]: draft } });
      setDraft(updated.helper_settings?.[kind] ?? draft);
      toast.success(t("saved"));
      return true;
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
      return false;
    }
  }
  useUnsavedChanges(`helper:${dataset.id}:${kind}`, {
    dirty,
    save,
    discard: () => setDraft(stored[kind]),
  });
  return (
    <Card className="min-w-0" data-tour={`datasets-${kind}-settings`}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <DatasetIcon tone={kind === "generator" ? "purple" : "green"} icon={Icon} />
          {t(`${kind}Title`)}
        </CardTitle>
        <CardDescription>{t(`${kind}Description`)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {draft.model_profile_id === null && (
          <p className="text-muted-foreground text-sm">{t("modelFallback")}</p>
        )}
        <PipelineModelPicker
          profiles={profiles}
          profilesStatus={profilesStatus}
          value={draft.model_profile_id}
          onChange={(model_profile_id) => setDraft((current) => ({ ...current, model_profile_id }))}
          allowAdd={can(Perm.connectionsManage)}
          disabled={disabled}
        />
        <MoreOptions label={ta("instructions")} defaultOpen={draft.instructions !== null}>
          <MarkdownEditor
            label={ta("instructions")}
            toolbar={<h3 className="text-sm font-medium">{ta("instructions")}</h3>}
            value={draft.instructions ?? dataset.helper_defaults?.[kind] ?? ""}
            rows={8}
            inertImages
            disabled={disabled}
            onChange={(instructions) => setDraft((current) => ({ ...current, instructions }))}
          />
        </MoreOptions>
        {dirty && (
          <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
            <Button variant="outline" onClick={() => setDraft(stored[kind])} disabled={disabled}>
              {tc("cancel")}
            </Button>
            <Button onClick={() => void save()} disabled={disabled}>
              {tc("save")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
