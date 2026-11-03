"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { Skill } from "@/types/providers";
import type { SkillAgentList } from "@/types/skill-versions";
import { eachAgentOnce } from "./skill-lines";

/** Who still uses the skill: the agents named, and how many more the reader cannot see. */
interface Users {
  names: string[];
  hidden: number;
}

/** The agents a refusal to delete names, from the server's `details`. */
function refusedBy(failure: unknown): Users | null {
  if (!(failure instanceof ApiError) || failure.code !== "IN_USE") return null;
  const agents = Array.isArray(failure.details?.agents) ? failure.details.agents : [];
  return {
    names: agents.flatMap((agent: unknown) =>
      typeof agent === "object" && agent !== null && "name" in agent
        ? [String((agent as { name: unknown }).name)]
        : [],
    ),
    hidden: Number(failure.details?.hidden ?? 0),
  };
}

/**
 * Delete a skill, but only one nobody uses.
 *
 * The agents table already says who uses it, so a used skill is not offered for
 * deletion at all: the dialog names the agents to move first. A refusal the server
 * still gives - an agent bound it meanwhile - is said here, under the same names.
 */
export function DeleteSkillDialog({
  skill,
  agents,
  deleting,
  onDelete,
  onClose,
}: {
  skill: Skill;
  agents: SkillAgentList | undefined;
  deleting: boolean;
  onDelete: () => Promise<void>;
  onClose: () => void;
}) {
  const t = useTranslations("skills.page.deleteSkill");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const [refused, setRefused] = useState<Users | null>(null);
  const [error, setError] = useState<string | null>(null);
  const known: Users = {
    names: eachAgentOnce(agents?.items ?? []).map((usage) => usage.agent.name),
    hidden: agents?.hidden ?? 0,
  };
  const users = refused ?? known;
  const used = users.names.length + users.hidden > 0;
  const list = new Intl.ListFormat(locale, { type: "conjunction" });

  async function confirm() {
    setError(null);
    try {
      await onDelete();
    } catch (failure) {
      const by = refusedBy(failure);
      if (by) setRefused(by);
      else setError(getErrorMessage(failure, tErrors));
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !deleting && onClose()}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("title", { name: skill.name })}</DialogTitle>
          <DialogDescription>{used ? t("used") : t("description")}</DialogDescription>
        </DialogHeader>
        {used && (
          <p role="alert" className="text-sm">
            {t("usedBy", {
              count: users.names.length + users.hidden,
              names: list.format(users.names),
              named: users.names.length > 0 ? "yes" : "no",
              hidden: users.hidden,
            })}
          </p>
        )}
        {error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={deleting} onClick={onClose}>
            {used ? t("close") : t("cancel")}
          </Button>
          {!used && (
            <Button variant="destructive" loading={deleting} onClick={() => void confirm()}>
              {t("delete")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
