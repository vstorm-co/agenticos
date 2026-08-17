"use client";

import { ArrowUpCircle, Plus, Trash2 } from "lucide-react";

import { DelegationModeField } from "@/components/agents/delegation-mode-field";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { useAgentVersions } from "@/hooks";
import { duplicateDelegateIds, pinStatus, type PinStatus } from "@/lib/agent-spec";
import type { Agent, DelegationMode, SubagentRef } from "@/types/agents";
import { useTranslations } from "next-intl";

interface DelegateListProps {
  /** The organization's agents, as the caller may see them. */
  agents: readonly Agent[];
  subagents: SubagentRef[];
  onChange: (subagents: SubagentRef[]) => void;
  /** Names claimed by more than one delegate or specialist. */
  clashes: ReadonlySet<string>;
  /**
   * Whether this caller may delegate at all.
   *
   * `agents:run`, because publishing checks each delegate against the
   * publisher's own right to run it. Without it the picker is not rendered:
   * offering a choice the publish step refuses is offering a dead end.
   */
  canDelegate: boolean;
  disabled?: boolean;
}

/**
 * The published agents this one may hand work to, each frozen at a version.
 *
 * The staleness line on each row is the reason this is not a plain multi-select.
 * A pin is what makes a delegate's behaviour stable under a published parent,
 * and the cost of that is that a fix to the delegate does not arrive - so
 * "somebody fixed the researcher and this agent kept getting the old answer"
 * has to be answerable *here*, on the row, with the way forward beside it.
 * Nothing else in the product would ever mention it.
 */
export function DelegateList({
  agents,
  subagents,
  onChange,
  clashes,
  canDelegate,
  disabled,
}: DelegateListProps) {
  const t = useTranslations("agents");
  const pinned = new Set(subagents.map((ref) => ref.agent_id));
  const duplicates = duplicateDelegateIds(subagents);
  // Only what can actually be pinned. An agent with no published version has no
  // version id to record; an archived one has stopped answering everywhere, so
  // pinning it would be pinning a delegate that cannot run; and one already on
  // the list would be the duplicate the spec's own validator refuses.
  const eligible = agents.filter(
    (agent) =>
      agent.current_version_id !== null && agent.status !== "archived" && !pinned.has(agent.id),
  );

  const patch = (index: number, changes: Partial<SubagentRef>) =>
    onChange(subagents.map((ref, at) => (at === index ? { ...ref, ...changes } : ref)));

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("delegatesHeading")}</p>
          <p className="text-muted-foreground text-xs">{t("delegatesDetail")}</p>
        </div>
        {canDelegate && (
          <AddDelegate
            eligible={eligible}
            disabled={disabled}
            onAdd={(agent) =>
              onChange([
                ...subagents,
                // Non-null by construction: `eligible` is filtered on it, and
                // the pin is the whole reason this reference exists.
                { agent_id: agent.id, agent_version_id: agent.current_version_id as string },
              ])
            }
          />
        )}
      </div>

      {subagents.length === 0 ? (
        <p className="text-muted-foreground border-border rounded-lg border border-dashed px-3 py-4 text-xs">
          {canDelegate ? t("noDelegatesYet") : t("delegatingNeedsRunPermission")}
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {subagents.map((ref, index) => (
            <DelegateRow
              key={`${ref.agent_id}-${index}`}
              reference={ref}
              agent={agents.find((agent) => agent.id === ref.agent_id)}
              duplicate={duplicates.has(ref.agent_id)}
              clashes={clashes}
              disabled={disabled}
              onModeChange={(preferred_mode) => patch(index, { preferred_mode })}
              onRepin={(agent_version_id) => patch(index, { agent_version_id })}
              onRemove={() => onChange(subagents.filter((_, at) => at !== index))}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * The way to add one, offering only what can be pinned.
 *
 * A menu rather than a select: picking a delegate is an action that appends to a
 * list, and a select would go on displaying the last agent chosen as though it
 * were the control's value.
 */
function AddDelegate({
  eligible,
  disabled,
  onAdd,
}: {
  eligible: readonly Agent[];
  disabled?: boolean;
  onAdd: (agent: Agent) => void;
}) {
  const t = useTranslations("agents");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled || eligible.length === 0}>
          <Plus className="h-3.5 w-3.5" />
          {t("addDelegate")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-72 scrollbar-thin overflow-y-auto">
        {eligible.map((agent) => (
          <DropdownMenuItem key={agent.id} onSelect={() => onAdd(agent)}>
            <span className="truncate">{agent.name}</span>
            <span className="text-muted-foreground font-mono text-xs">{agent.slug}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface DelegateRowProps {
  reference: SubagentRef;
  /** Absent when the organization no longer has it, or this caller cannot see it. */
  agent: Agent | undefined;
  duplicate: boolean;
  clashes: ReadonlySet<string>;
  disabled?: boolean;
  onModeChange: (mode: DelegationMode | null) => void;
  onRepin: (versionId: string) => void;
  onRemove: () => void;
}

/**
 * One delegate: what it is called, where its pin stands, and how it is called.
 *
 * It reads the delegate's own version history rather than taking it as a prop.
 * Answering "how far behind is this pin" needs the numbers behind two ids, and
 * they are the delegate's history - fetched per row because there is one request
 * per delegate either way, and a parent assembling them would have to know how
 * many rows it had before it could ask.
 */
function DelegateRow({
  reference,
  agent,
  duplicate,
  clashes,
  disabled,
  onModeChange,
  onRepin,
  onRemove,
}: DelegateRowProps) {
  const t = useTranslations("agents");
  const { versions } = useAgentVersions(agent === undefined ? null : reference.agent_id);
  const latest = agent?.current_version_id ?? null;
  const status = pinStatus(versions, reference.agent_version_id, latest);
  // Both are a pin that will not do what its author thinks, and both are fixed
  // the same way. `gone` is the worse of the two - it fails the run outright,
  // naming the delegate, because a silent fall back to the current version is
  // exactly what pinning exists to prevent.
  const stale = status.kind === "behind" || status.kind === "gone";

  return (
    <li
      // Named, and named by the handle rather than by the display name: every
      // row carries the same controls, so without this a screen reader announces
      // one identical "When it hands back" select per delegate and none of them
      // says which delegate it belongs to. The handle is what the model
      // addresses, what a validation error names, and what a rename does not
      // move.
      aria-label={agent?.slug ?? reference.agent_id}
      className="space-y-2 p-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{agent?.name ?? t("delegateUnreachable")}</p>
          <p className="text-muted-foreground font-mono text-xs">
            {agent?.slug ?? reference.agent_id}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <PinBadge status={status} />
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled}
            aria-label={t("removeDelegate", { name: agent?.name ?? reference.agent_id })}
            onClick={onRemove}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {agent === undefined && (
        <p className="text-destructive text-xs">{t("delegateUnreachableDetail")}</p>
      )}
      {duplicate && <p className="text-destructive text-xs">{t("delegatePinnedTwice")}</p>}
      {agent !== undefined && clashes.has(agent.slug) && (
        <p className="text-destructive text-xs">{t("delegateNameClash", { name: agent.slug })}</p>
      )}

      {stale && latest !== null && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs">
            {status.kind === "behind"
              ? t("delegatePinBehind", {
                  by: status.by,
                  version: status.version,
                  latest: status.latest,
                })
              : t("delegatePinGoneDetail")}
          </p>
          <Button variant="outline" size="sm" disabled={disabled} onClick={() => onRepin(latest)}>
            <ArrowUpCircle className="h-3.5 w-3.5" />
            {t("updateToLatest")}
          </Button>
        </div>
      )}

      <DelegationModeField
        id={`delegate-${reference.agent_id}-mode`}
        value={reference.preferred_mode ?? null}
        disabled={disabled}
        onChange={onModeChange}
      />
    </li>
  );
}

/** Where a pin stands, in the fewest words that still name the consequence. */
function PinBadge({ status }: { status: PinStatus }) {
  const t = useTranslations("agents");
  switch (status.kind) {
    case "current":
      return <Badge variant="outline">{t("pinCurrent", { version: status.version })}</Badge>;
    case "behind":
      return <Badge variant="secondary">{t("pinBehind", { by: status.by })}</Badge>;
    case "gone":
      return <Badge variant="destructive">{t("pinGone")}</Badge>;
    case "unknown":
      return <Badge variant="outline">{t("pinUnknown")}</Badge>;
  }
}
