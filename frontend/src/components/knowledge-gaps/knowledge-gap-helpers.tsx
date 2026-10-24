"use client";

import { useState } from "react";
import { Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SystemAgentChoice } from "@/components/agents/system-agent-choice";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { KnowledgeBase } from "@/types/knowledge-base";

export interface GapHelpers {
  gap_drafter_agent_id: string | null;
  gap_classifier_agent_id: string | null;
}

/** Per-base helpers, using the same agent picker as Improve and case generation. */
export function KnowledgeGapHelpers({
  kb,
  onSave,
}: {
  kb: Pick<KnowledgeBase, "name" | "gap_drafter_agent_id" | "gap_classifier_agent_id">;
  onSave: (data: GapHelpers) => Promise<unknown>;
}) {
  const t = useTranslations("agents.systemChoice");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <Settings2 className="size-3.5" aria-hidden />
        {t("helpers")}
      </Button>
      {open && <HelpersDialog kb={kb} onSave={onSave} onOpenChange={setOpen} />}
    </>
  );
}

function HelpersDialog({
  kb,
  onSave,
  onOpenChange,
}: {
  kb: Pick<KnowledgeBase, "name" | "gap_drafter_agent_id" | "gap_classifier_agent_id">;
  onSave: (data: GapHelpers) => Promise<unknown>;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("agents.systemChoice");
  const tErrors = useTranslations("errors");
  const [drafter, setDrafter] = useState(kb.gap_drafter_agent_id ?? null);
  const [classifier, setClassifier] = useState(kb.gap_classifier_agent_id ?? null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onSave({ gap_drafter_agent_id: drafter, gap_classifier_agent_id: classifier });
      toast.success(t("saved"));
      onOpenChange(false);
    } catch (failure) {
      setError(getErrorMessage(failure, tErrors));
    } finally {
      setSaving(false);
    }
  }
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("helpers")}</DialogTitle>
          <DialogDescription>{t("helpersBody", { name: kb.name })}</DialogDescription>
        </DialogHeader>
        <SystemAgentChoice
          kind="classifier"
          value={classifier}
          onChange={setClassifier}
          disabled={saving}
        />
        <SystemAgentChoice kind="drafter" value={drafter} onChange={setDrafter} disabled={saving} />
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            {t("cancel")}
          </Button>
          <Button onClick={() => void save()} disabled={saving}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
