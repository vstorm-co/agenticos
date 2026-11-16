"use client";

import { normalizeIdentifier } from "@/lib/normalize-identifier";
import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Textarea,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import type { ProposedSkill, RejectedChange } from "@/types/authoring";

/** Below this many distinct answers the assistant does not add a new skill on its own. */
const RECORDED_FROM_ANSWERS = 3;
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** A model's "Refund Policy Summary" as the skill library's `refund-policy-summary`. */
export function skillSlug(name: string): string {
  return normalizeIdentifier(name).slice(0, 64).replace(/-+$/g, "");
}

/**
 * The skill an idea proposed, editable before a person creates it. Creating it
 * adds it to the library and to the agent's draft; nothing is published.
 */
export function IdeaSkillDialog({
  change,
  onCreate,
  onOpenChange,
}: {
  change: RejectedChange["change"];
  /** False when nothing was created and the dialog should stay open. */
  onCreate: (skill: ProposedSkill) => Promise<boolean>;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("authoring.rejected.create");
  const tErrors = useTranslations("errors");
  const [name, setName] = useState(() => skillSlug(change.name ?? ""));
  const [description, setDescription] = useState(change.description ?? "");
  const [content, setContent] = useState(change.content ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const answers = change.answers ?? 0;
  const nameValid = SKILL_NAME.test(normalizeIdentifier(name));
  const ready = nameValid && description.trim() !== "" && content.trim() !== "" && !busy;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (
        await onCreate({
          name: normalizeIdentifier(name),
          description: description.trim(),
          content,
        })
      )
        onOpenChange(false);
    } catch (failure) {
      setError(getErrorMessage(failure, tErrors));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_CANVAS} ${DIALOG_FILL}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className={`${DIALOG_BODY} space-y-4`}>
          {answers < RECORDED_FROM_ANSWERS && (
            <p role="status" className="text-warning-ink text-sm">
              {t("fewAnswers", { count: answers })}
            </p>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="idea-skill-name">{t("name")}</Label>
            <Input
              id="idea-skill-name"
              value={name}
              maxLength={64}
              aria-describedby="idea-skill-name-hint"
              onChange={(event) => setName(event.target.value)}
              onBlur={() => setName(normalizeIdentifier(name))}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
            />
            <p id="idea-skill-name-hint" className="text-muted-foreground text-xs">
              {t("nameHint")}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-skill-description">{t("summary")}</Label>
            <Input
              id="idea-skill-description"
              value={description}
              maxLength={500}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idea-skill-content">{t("content")}</Label>
            <Textarea
              id="idea-skill-content"
              rows={12}
              value={content}
              onChange={(event) => setContent(event.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="text-destructive-ink text-sm">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={!ready} onClick={() => void submit()}>
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
