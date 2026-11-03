"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
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
 * changes nothing it reads yet. Each move is a Change version: a new published
 * version of the agent, or a draft change where the person may not publish it.
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
  const { createFork, changeBinding } = useSkillVersionWrites(skill.id);
  const [name, setName] = useState("");
  const [moving, setMoving] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const movable = agents.filter(
    (usage) => usage.can_change && !usage.draft_only && usage.via_specialist === null,
  );
  const busy = createFork.isPending || changeBinding.isPending;

  async function create() {
    setError(null);
    let forkId: string;
    try {
      forkId = (await createFork.mutateAsync({ name: name.trim(), fromVersionId: baseId })).id;
    } catch (failure) {
      setError(getErrorMessage(failure, tErrors));
      return;
    }
    let moved = 0;
    for (const usage of movable.filter((one) => moving.includes(one.agent.id))) {
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
          <DialogDescription>{t("description", { number: skill.version })}</DialogDescription>
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
        {error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button loading={busy} disabled={name.trim() === ""} onClick={() => void create()}>
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
