"use client";

import { useState } from "react";
import Link from "next/link";
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
import { ROUTES } from "@/lib/constants";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { Skill } from "@/types/providers";
import type { SkillAgentList } from "@/types/skill-versions";
import { eachAgentOnce } from "./skill-lines";

/**
 * Who still uses the skill: the agents named, how many more the reader cannot see,
 * and the named ones the reader may not change.
 */
interface Users {
  names: string[];
  hidden: number;
  locked: string[];
  /** Agents an environment waiting for promotion still serves the skill to, by environment. */
  waiting: { name: string; environments: string[] }[];
}

const namesIn = (value: unknown): string[] =>
  (Array.isArray(value) ? value : []).flatMap((agent: unknown) =>
    typeof agent === "object" && agent !== null && "name" in agent
      ? [String((agent as { name: unknown }).name)]
      : [],
  );

/** The agents a refusal to delete names, from the server's `details`. */
function refusedBy(failure: unknown): Users | null {
  if (!(failure instanceof ApiError) || failure.code !== "IN_USE") return null;
  return {
    names: namesIn(failure.details?.agents),
    hidden: Number(failure.details?.hidden ?? 0),
    locked: namesIn(failure.details?.not_editable),
    waiting: (Array.isArray(failure.details?.waiting) ? failure.details.waiting : []).map(
      (agent: { name: string; environments: string[] }) => ({
        name: agent.name,
        environments: agent.environments,
      }),
    ),
  };
}

/** The agent whose newest spec does not publish without the skill, when that refused it. */
function unpublishable(failure: unknown): { id: string; name: string } | null {
  if (!(failure instanceof ApiError) || typeof failure.details?.agent_name !== "string") {
    return null;
  }
  return { id: String(failure.details.agent_id), name: failure.details.agent_name };
}

/**
 * Delete a skill, taking it off the agents that use it first.
 *
 * The agents table already says who uses it, so a used skill names them here, and
 * offers to take it off all of them and delete it - after a second confirmation,
 * since every one of those agents changes. That is offered only when the reader may
 * change every agent and sees them all; otherwise the dialog names who stands in
 * the way. A refusal the server still gives - an agent bound it meanwhile - is said
 * here, under the same names. Nothing is offered while the agents are still on their
 * way; when they could not be read, deleting is offered and the server still guards it.
 */
export function DeleteSkillDialog({
  skill,
  agents,
  agentsError,
  deleting,
  onDelete,
  onClose,
}: {
  skill: Skill;
  agents: SkillAgentList | undefined;
  /** Why the agents could not be read, when they could not. */
  agentsError: unknown;
  deleting: boolean;
  /** Deletes the skill; with `removeFromAgents`, after taking it off every agent using it. */
  onDelete: (removeFromAgents: boolean) => Promise<void>;
  onClose: () => void;
}) {
  const t = useTranslations("skills.page.deleteSkill");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const [refused, setRefused] = useState<Users | null>(null);
  const [stuck, setStuck] = useState<{ id: string; name: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rows = eachAgentOnce(agents?.items ?? []);
  const known: Users = {
    names: rows.map((usage) => usage.agent.name),
    hidden: agents?.hidden ?? 0,
    locked: rows.filter((usage) => !usage.can_change).map((usage) => usage.agent.name),
    waiting: [],
  };
  const users = refused ?? known;
  const count = users.names.length + users.hidden;
  const used = count > 0;
  const removable =
    used && users.hidden === 0 && users.locked.length === 0 && users.waiting.length === 0;
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const checking = agents === undefined && !agentsError && refused === null;

  async function confirm(removeFromAgents: boolean) {
    setError(null);
    try {
      await onDelete(removeFromAgents);
    } catch (failure) {
      setConfirming(false);
      setStuck(unpublishable(failure));
      // An agent took the skill up while it was being removed: the same delete may pass now.
      if (failure instanceof ApiError && failure.details?.reason === "agents_changed") {
        setError(t("agentsChanged"));
        return;
      }
      const by = refusedBy(failure);
      if (by) setRefused(by);
      else if (!unpublishable(failure)) setError(getErrorMessage(failure, tErrors));
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !deleting && onClose()}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("title", { name: skill.name })}</DialogTitle>
          <DialogDescription>
            {confirming ? t("removeBody", { count }) : used ? t("used") : t("description")}
          </DialogDescription>
        </DialogHeader>
        {used && confirming && (
          <ul className="list-disc space-y-0.5 pl-5 text-sm">
            {users.names.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        )}
        {used && !confirming && (
          <p role="alert" className="text-sm">
            {t("usedBy", {
              count,
              names: list.format(users.names),
              named: users.names.length > 0 ? "yes" : "no",
              hidden: users.hidden,
            })}
          </p>
        )}
        {used && !confirming && users.locked.length > 0 && (
          <p className="text-muted-foreground text-sm">
            {t("locked", { names: list.format(users.locked), count: users.locked.length })}
          </p>
        )}
        {used && !confirming && users.hidden > 0 && (
          <p className="text-muted-foreground text-sm">{t("hiddenBlocks")}</p>
        )}
        {users.waiting.map((agent) => (
          <p key={agent.name} className="text-muted-foreground text-sm">
            {t("waiting", {
              name: agent.name,
              environments: list.format(agent.environments),
              count: agent.environments.length,
            })}
          </p>
        ))}
        {stuck !== null && (
          <p role="alert" className="text-destructive text-sm">
            {t.rich("unpublishable", {
              name: stuck.name,
              link: (chunks) => (
                <Link className="underline underline-offset-4" href={ROUTES.AGENT_DETAIL(stuck.id)}>
                  {chunks}
                </Link>
              ),
            })}
          </p>
        )}
        {checking && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("checking")}
          </p>
        )}
        {agents === undefined && Boolean(agentsError) && !used && (
          <p className="text-muted-foreground text-sm">{t("unread")}</p>
        )}
        {error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            disabled={deleting}
            onClick={confirming ? () => setConfirming(false) : onClose}
          >
            {confirming ? t("back") : t("cancel")}
          </Button>
          {!used && (
            <Button
              variant="destructive"
              loading={deleting}
              disabled={checking}
              onClick={() => void confirm(false)}
            >
              {t("delete")}
            </Button>
          )}
          {removable && (
            <Button
              variant="destructive"
              loading={deleting}
              onClick={confirming ? () => void confirm(true) : () => setConfirming(true)}
            >
              {confirming ? t("removeConfirm") : t("removeAndDelete", { count })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
