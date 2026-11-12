"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";
import { useSkillVersionWrites } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { Skill } from "@/types/providers";
import type { SkillAgentUsage } from "@/types/skill-versions";
import { bindingLabel } from "./skill-lines";

/**
 * Start a fork from main's newest version, and move agents onto it if asked.
 *
 * The fork serves that version unchanged until it is edited, so moving an agent
 * that reads it already changes nothing yet; an agent pinned to an older version
 * or on another fork reads new content, and the person accepts that first. Each
 * move is a Change version: a new published version of the agent, or a draft
 * change where the person may not publish it. Main is read again before the fork
 * is made, so one saved meanwhile is said rather than skipped.
 */
export function NewForkDialog({
  skill,
  baseId,
  agents,
  onClose,
  onCreated,
}: {
  skill: Skill;
  /** Main's newest version, which the fork starts from. */
  baseId: string;
  /** The skill's agents; only those whose own binding may be changed are offered. */
  agents: SkillAgentUsage[];
  onClose: () => void;
  onCreated: (forkId: string) => void;
}) {
  const t = useTranslations("skills.page.newFork");
  const tPage = useTranslations("skills.page");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { createFork, changeBinding, mainLatest } = useSkillVersionWrites(skill.id);
  const [base, setBase] = useState({ id: baseId, number: skill.version });
  const [understood, setUnderstood] = useState(false);
  const [name, setName] = useState("");
  const [moving, setMoving] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const movable = agents.filter(
    (usage) => usage.can_change && !usage.draft_only && usage.via_specialist === null,
  );
  const busy = createFork.isPending || changeBinding.isPending;
  const moves = movable.filter((usage) => moving.includes(usage.agent.id));
  // Everyone but the agents already reading main's newest version gets new content.
  const changing = moves.filter(
    (usage) =>
      usage.binding.version.fork_id !== null || usage.binding.version.number !== base.number,
  );
  const list = new Intl.ListFormat(locale, { type: "conjunction" });

  async function create() {
    setError(null);
    let forkId: string;
    try {
      const now = await mainLatest();
      if (now.id !== null && now.id !== base.id) {
        setBase({ id: now.id, number: now.number });
        setUnderstood(false);
        setError(t("mainMoved", { number: now.number }));
        return;
      }
      forkId = (await createFork.mutateAsync({ name: name.trim(), fromVersionId: base.id })).id;
    } catch (failure) {
      setError(getErrorMessage(failure, tErrors));
      return;
    }
    let moved = 0;
    for (const usage of moves) {
      try {
        await changeBinding.mutateAsync({
          agentId: usage.agent.id,
          target: { state: "fork", fork_id: forkId },
        });
        moved += 1;
      } catch (failure) {
        toast.error(
          t("moveFailed", { name: usage.agent.name, reason: getErrorMessage(failure, tErrors) }),
        );
      }
    }
    toast.success(t("created", { name: name.trim(), moved }));
    onCreated(forkId);
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("title", { name: skill.name })}</DialogTitle>
          <DialogDescription>{t("description", { number: base.number })}</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="new-fork-name">{t("name")}</Label>
          <Input
            id="new-fork-name"
            value={name}
            maxLength={64}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("agents")}</legend>
          {movable.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noAgents")}</p>
          ) : (
            <>
              <p className="text-muted-foreground text-xs">{t("agentsHint")}</p>
              {movable.map((usage) => (
                <div key={usage.agent.id} className="flex items-center gap-2">
                  <Checkbox
                    id={`new-fork-agent-${usage.agent.id}`}
                    checked={moving.includes(usage.agent.id)}
                    onCheckedChange={(checked) =>
                      setMoving((current) =>
                        checked === true
                          ? [...current, usage.agent.id]
                          : current.filter((id) => id !== usage.agent.id),
                      )
                    }
                  />
                  <Label htmlFor={`new-fork-agent-${usage.agent.id}`} className="font-normal">
                    {t("agentNow", {
                      name: usage.agent.name,
                      binding: bindingLabel(tPage, usage.binding),
                    })}
                  </Label>
                </div>
              ))}
            </>
          )}
        </fieldset>
        {changing.length > 0 && (
          <div className="flex items-start gap-2 rounded-lg border p-3">
            <Checkbox
              id="new-fork-understood"
              checked={understood}
              onCheckedChange={(checked) => setUnderstood(checked === true)}
            />
            <Label htmlFor="new-fork-understood" className="leading-snug font-normal">
              {t("changesContent", {
                names: list.format(changing.map((usage) => usage.agent.name)),
                count: changing.length,
                number: base.number,
              })}
            </Label>
          </div>
        )}
        {error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            loading={busy}
            disabled={name.trim() === "" || (changing.length > 0 && !understood)}
            onClick={() => void create()}
          >
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
