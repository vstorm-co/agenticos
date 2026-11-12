"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
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
import { useSkillAgents } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { SkillCheck } from "@/types/skill-checks";
import { shownState } from "./check-summary";

/** What saving the change as a fork sends: its name and the agents that move onto it. */
export interface ForkChoice {
  name: string;
  agent_ids: string[];
}

/**
 * Saving a checked change as a fork, offered whatever the check found. The person
 * names it and picks the agents that move onto it - the ones it helped to begin with,
 * any others, or none. An agent reading the skill through a specialist moves in its
 * Builder, so it is not offered here; one the reader may not change is shown but
 * stays on its version, and agents the reader may not see stay where they are. Which
 * agents the reader may change comes from the skill's agents, so nothing is picked or
 * sent until they load. A refused fork keeps the dialog open with the refusal.
 */
export function ForkDialog({
  skillId,
  check,
  attempt,
  disabled,
  busy,
  onFork,
}: {
  skillId: string;
  check: SkillCheck;
  attempt: number;
  disabled: boolean;
  busy: boolean;
  /** Resolves to why the fork was refused, or null once it was made. */
  onFork: (choice: ForkChoice) => Promise<string | null>;
}) {
  const t = useTranslations("skillImprovement.accept");
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="outline" disabled={disabled} onClick={() => setOpen(true)}>
        {t("fork.open")}
      </Button>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        {open && (
          <ForkForm
            skillId={skillId}
            check={check}
            attempt={attempt}
            busy={busy}
            onFork={async (choice) => {
              const refused = await onFork(choice);
              if (refused === null) setOpen(false);
              return refused;
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ForkForm({
  skillId,
  check,
  attempt,
  busy,
  onFork,
}: {
  skillId: string;
  check: SkillCheck;
  attempt: number;
  busy: boolean;
  onFork: (choice: ForkChoice) => Promise<string | null>;
}) {
  const t = useTranslations("skillImprovement.accept");
  const tState = useTranslations("skillImprovement.agents.state");
  const tErrors = useTranslations("errors");
  const tCommon = useTranslations("common");
  const { agents: usages, error, retry, retrying } = useSkillAgents(skillId);
  const [refusal, setRefusal] = useState<string | null>(null);
  const movable = check.agents.filter((row) => row.via_specialist === null);
  const throughSpecialist = check.agents.length - movable.length;
  const helped = movable.filter((row) => row.state === "better");
  const [name, setName] = useState(helped[0]?.agent.name ?? t("fork.defaultName", { attempt }));
  const [picked, setPicked] = useState(() => new Set(helped.map((row) => row.agent.id)));
  const toggle = (id: string, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const usageOf = (id: string) => usages?.items.find((usage) => usage.agent.id === id);
  const ready = usages !== undefined;
  const locked = (id: string) => usageOf(id)?.can_change !== true;
  const moving = ready ? [...picked].filter((id) => !locked(id)) : [];

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("fork.title")}</DialogTitle>
        <DialogDescription>{t("fork.description")}</DialogDescription>
      </DialogHeader>
      <div className={`${DIALOG_BODY} space-y-4`}>
        <div className="space-y-2">
          <Label htmlFor="skill-accept-fork">{t("forkName")}</Label>
          <Input
            id="skill-accept-fork"
            value={name}
            maxLength={64}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">{t("fork.agents")}</legend>
          {movable.map((row) => {
            const usage = usageOf(row.agent.id)?.agent;
            const id = `skill-accept-fork-${row.agent.id}`;
            const stays = ready && locked(row.agent.id);
            return (
              <div key={row.agent.id} className="flex items-center gap-2">
                <Checkbox
                  id={id}
                  checked={ready && picked.has(row.agent.id) && !stays}
                  disabled={!ready || stays}
                  onCheckedChange={(checked) => toggle(row.agent.id, checked === true)}
                />
                <AgentAvatar
                  agentId={row.agent.id}
                  slug={usage?.slug ?? row.agent.id}
                  hasAvatar={usage?.has_avatar}
                  colorSlot={usage?.avatar_color}
                  size="sm"
                />
                <Label htmlFor={id} className="flex-1 font-normal">
                  {row.agent.name}
                </Label>
                <span className="text-muted-foreground text-xs">
                  {stays ? t("fork.stays") : tState(shownState(row.state))}
                </span>
              </div>
            );
          })}
          {throughSpecialist > 0 && (
            <p className="text-muted-foreground text-xs">
              {t("fork.throughSpecialist", { count: throughSpecialist })}
            </p>
          )}
          {check.hidden > 0 && (
            <p className="text-muted-foreground text-xs">
              {t("fork.hidden", { count: check.hidden })}
            </p>
          )}
        </fieldset>
        {error && !ready && (
          <div className="flex items-center gap-2">
            <p role="alert" className="text-destructive flex-1 text-sm">
              {getErrorMessage(error, tErrors)}
            </p>
            <Button variant="outline" size="sm" loading={retrying} onClick={() => void retry()}>
              {tCommon("retry")}
            </Button>
          </div>
        )}
        {refusal !== null && (
          <p role="alert" className="text-destructive text-sm">
            {refusal}
          </p>
        )}
      </div>
      <DialogFooter>
        <Button
          disabled={name.trim() === "" || !ready}
          loading={busy}
          onClick={() => void onFork({ name: name.trim(), agent_ids: moving }).then(setRefusal)}
        >
          {t("fork.submit", { count: moving.length })}
        </Button>
      </DialogFooter>
    </>
  );
}
