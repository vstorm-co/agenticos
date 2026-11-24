"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useSkills } from "@/hooks/use-skills";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import type { ProposalCreate, ProposalTargetType } from "@/lib/failure-learning-api";

/**
 * Propose one rule-text change: what it replaces, what replaces it, and
 * why. A skill target names the skill; an instruction target changes this
 * agent only. The try that evidences it is linked, never re-typed.
 */
export function ProposalForm({
  ledgerEntryId,
  evalTryId,
  initialNewText,
  onSubmit,
  onCancel,
}: {
  ledgerEntryId: string | null;
  evalTryId: string | null;
  initialNewText: string;
  onSubmit: (input: ProposalCreate) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("failureLearning");
  const { skills } = useSkills({});
  const [target, setTarget] = useState<ProposalTargetType>("instructions");
  const [skillId, setSkillId] = useState("");
  const [oldText, setOldText] = useState("");
  const [newText, setNewText] = useState(initialNewText);
  const [rationale, setRationale] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("newProposal")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({
              ledger_entry_id: ledgerEntryId,
              eval_try_id: evalTryId,
              target: { type: target, skill_id: target === "skill" ? skillId : null },
              old_text: oldText.trim(),
              new_text: newText.trim(),
              rationale: rationale.trim(),
            });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="proposal-target">{t("proposalTarget")}</Label>
            <Select value={target} onValueChange={(next) => setTarget(next as ProposalTargetType)}>
              <SelectTrigger id="proposal-target">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="instructions">{t("targetInstructions")}</SelectItem>
                <SelectItem value="skill">{t("targetSkill")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {target === "skill" && (
            <div className="space-y-1.5">
              <Label htmlFor="proposal-skill">{t("targetSkill")}</Label>
              <Select value={skillId} onValueChange={setSkillId}>
                <SelectTrigger id="proposal-skill">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {skills.map((skill) => (
                    <SelectItem key={skill.id} value={skill.id}>
                      {skill.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="proposal-old">{t("oldTextLabel")}</Label>
            <Textarea
              id="proposal-old"
              value={oldText}
              onChange={(event) => setOldText(event.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="proposal-new">{t("newTextLabel")}</Label>
            <Textarea
              id="proposal-new"
              value={newText}
              onChange={(event) => setNewText(event.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="proposal-why">{t("rationaleLabel")}</Label>
            <Textarea
              id="proposal-why"
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              placeholder={t("rationalePlaceholder")}
              required
            />
          </div>
          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={
                oldText.trim() === "" ||
                newText.trim() === "" ||
                rationale.trim() === "" ||
                (target === "skill" && skillId === "")
              }
            >
              {t("create")}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("cancel")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
