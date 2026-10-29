"use client";

import { useTranslations } from "next-intl";

import { badgeVariants } from "@/components/ui";
import { changeGroup, editedOnAccept, grouped, oneSentence } from "@/lib/authoring-groups";
import type { Hunk, HunkDecision, ProposedSkill, RejectedChange } from "@/types/authoring";
import { ChangeExpander, type DecidedState } from "./change-expander";
import { useChangeLabel } from "./change-label";
import { IdeaCard } from "./idea-card";
import { SuggestionCard } from "./suggestion-card";

/** A suggestion in the open batch, or a new-skill idea on the latest request's report. */
export type Entry = { hunk: Hunk } | { idea: RejectedChange; index: number; requestId: string };

export interface EntryActions {
  /** Whether the batch is still open, so its suggestions may be decided and undone. */
  open: boolean;
  busy: boolean;
  onDecide: (hunk: Hunk, decision: HunkDecision) => void;
  /** The stored draft's instructions, for editing a suggestion in all of them. */
  instructions?: string;
  onCreateIdea?: (requestId: string, index: number, skill: ProposedSkill) => Promise<boolean>;
  onDecideIdea: (requestId: string, index: number, action: "dismiss" | "undo") => void;
}

/**
 * Changes grouped by kind - instructions, tools, settings, new skills - each group
 * headed by its name and count. Waiting ones are shown whole; decided ones fold
 * to a line naming the change, how it was decided and what it was for.
 */
export function ChangeGroups({
  entries,
  decided,
  actions,
}: {
  entries: Entry[];
  decided: boolean;
  actions: EntryActions;
}) {
  const t = useTranslations("authoring.tabs.group");
  return (
    <div className="space-y-5">
      {grouped(entries, (entry) => ("hunk" in entry ? changeGroup(entry.hunk.kind) : "skills")).map(
        ([group, members]) => (
          <section key={group} className="space-y-2" aria-label={t(group)}>
            <h3 className="flex items-center gap-2 text-sm font-medium">
              {t(group)}{" "}
              <span className={badgeVariants({ variant: "secondary" })}>{members.length}</span>
            </h3>
            {members.map((entry) => (
              <EntryView
                key={
                  "hunk" in entry ? `${entry.hunk.id}-${entry.hunk.status}` : `idea-${entry.index}`
                }
                entry={entry}
                decided={decided}
                actions={actions}
              />
            ))}
          </section>
        ),
      )}
    </div>
  );
}

function EntryView({
  entry,
  decided,
  actions,
}: {
  entry: Entry;
  decided: boolean;
  actions: EntryActions;
}) {
  const label = useChangeLabel();
  const tKind = useTranslations("improvement.changeKind");
  if ("idea" in entry) {
    const create = actions.onCreateIdea;
    const card = (
      <IdeaCard
        item={entry.idea}
        busy={actions.busy}
        onCreate={create && ((skill) => create(entry.requestId, entry.index, skill))}
        onDecide={(action) => actions.onDecideIdea(entry.requestId, entry.index, action)}
      />
    );
    if (!decided) return card;
    return (
      <ChangeExpander
        label={tKind("skill")}
        state={entry.idea.skill_id ? "created" : "dismissed"}
        summary={entry.idea.change.name ?? ""}
      >
        {card}
      </ChangeExpander>
    );
  }
  const { hunk } = entry;
  const card = (
    <SuggestionCard
      hunk={hunk}
      canEdit={actions.open}
      busy={actions.busy}
      onDecide={(decision) => actions.onDecide(hunk, decision)}
      instructions={actions.instructions}
      folded={decided}
    />
  );
  if (!decided) return card;
  return (
    <ChangeExpander label={label(hunk)} state={stateOf(hunk)} summary={oneSentence(hunk)}>
      {card}
    </ChangeExpander>
  );
}

function stateOf(hunk: Hunk): DecidedState {
  if (hunk.status === "dismissed") return "dismissed";
  if (hunk.status === "pending") return "notDecided";
  return editedOnAccept(hunk) ? "edited" : "accepted";
}
