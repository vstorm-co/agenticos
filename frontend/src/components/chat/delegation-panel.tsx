"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronDown, CopyPlus, Users } from "lucide-react";
import { toast } from "sonner";

import { useAgents, useModelProviders, usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { newSpecialist, specialistNameError } from "@/lib/agent-spec";
import { cn, getErrorMessage } from "@/lib/utils";
import { childrenOf, rootsOf } from "@/lib/delegations";
import { toolStep } from "@/lib/tool-steps";
import { Button } from "@/components/ui";
import { Perm } from "@/types/permissions";
import type { Delegation, DelegationStatus, SpecialistDefinition } from "@/types";
import { AgentStep } from "./agent-step";
import { MarkdownContent } from "./markdown-content";

/**
 * What the specialists are doing, one collapsible block per delegation.
 *
 * **One panel per `task_id`, never interleaved text.** A fan-out is three
 * specialists generating at once, and their deltas arrive on one socket in
 * whatever order the models produce them - folded into the transcript they read as
 * one paragraph written by three people, which is worse than no streaming at all.
 * `task_id` is the whole reason the contract carries one.
 *
 * **Its own block, not part of the assistant's message.** A child's text is not the
 * parent's answer: inlining it would put words in the parent's mouth that its own
 * model never generated, and the conversation is persisted from that message.
 *
 * **Nested by depth.** A specialist that delegates further is legal up to
 * `max_depth`, and "the researcher is working" and "the researcher's own assistant
 * is working" are different sentences.
 */
export function DelegationPanels({ delegations }: { delegations: Delegation[] }) {
  if (delegations.length === 0) return null;
  return (
    <div className="space-y-1 pb-2">
      {rootsOf(delegations).map((delegation) => (
        <DelegationPanel key={delegation.taskId} delegation={delegation} all={delegations} />
      ))}
    </div>
  );
}

/**
 * How the delegate's name reads at a glance.
 *
 * A table rather than a chain of conditions: the four statuses are exhaustive, so
 * there is nothing to fall through to and nothing to test about falling through.
 */
const TONE: Record<DelegationStatus, string> = {
  running: "text-brand animate-pulse",
  completed: "text-muted-foreground/70",
  failed: "text-destructive",
  cancelled: "text-muted-foreground/70",
  // The amber a parked tool call uses (`AgentStep`'s `parked` state): waiting for a
  // person, not working and not done - and never a spinner, which is a lie that
  // does not resolve until somebody decides.
  awaiting_approval: "text-amber-600",
};

/**
 * The catalog key for each status - keys here, translated at the point of use.
 *
 * A module-level table cannot call a translator, and holding English here would put
 * four strings outside `messages/` where no translation reaches them.
 */
const STATUS_KEY: Record<DelegationStatus, string> = {
  running: "working",
  completed: "finished",
  failed: "failed",
  cancelled: "stopped",
  awaiting_approval: "awaiting",
};

/**
 * One delegation: who is working, on what, and what it cost.
 *
 * Open while it runs and closed once it is over, which is the rule the tool steps
 * follow too: what somebody is watching is worth the room, and what has finished is
 * worth a line they can open. The header keeps the name, the outcome and the cost
 * either way, so closing hides nothing a reader needs in order to decide to look.
 */
function DelegationPanel({ delegation, all }: { delegation: Delegation; all: Delegation[] }) {
  const t = useTranslations("chat.delegation");
  const tTools = useTranslations("chat.tools");
  const { can } = usePermissions();
  const [open, setOpen] = useState(delegation.status === "running");
  // The render-time transition `ToolCallCard` uses rather than an effect: a panel
  // that has finished must not be shown open for a frame first. Comparing against
  // the status last *seen* is also what keeps a replayed delegation - mounted
  // already finished - closed, where an effect on `status` would close it after a
  // visible frame and `useChanged` would report the mount pass as a change.
  //
  // Closed on *any* change rather than on a change to a terminal status: the only
  // transition a delegation can make is `running` to one of the three outcomes -
  // no frame puts it back - so a condition on that would be a branch nothing can
  // take, and this codebase's coverage gate is right to notice one.
  const [seen, setSeen] = useState(delegation.status);
  if (seen !== delegation.status) {
    setSeen(delegation.status);
    setOpen(false);
  }

  const children = childrenOf(all, delegation.taskId);

  return (
    <div className="border-foreground/10 border-l pl-3.5">
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        aria-expanded={open}
        className="hover:text-foreground flex max-w-full min-w-0 items-center gap-2 rounded-md py-1 text-left"
      >
        <Users className={cn("h-3.5 w-3.5 shrink-0", TONE[delegation.status])} aria-hidden />
        <span className="text-foreground/80 min-w-0 truncate text-[13px] font-medium">
          {delegation.subagent}
        </span>
        <span className="text-muted-foreground shrink-0 text-[13px]">
          {t(STATUS_KEY[delegation.status])}
        </span>
        {/* A background delegation reports *after* the parent has answered, so
            saying which kind it is at the start is what stops the panel reading as
            an answer that never arrived. */}
        {delegation.mode === "async" && (
          <span className="text-muted-foreground/60 shrink-0 font-mono text-[10px] tracking-wider uppercase">
            {t("background")}
          </span>
        )}
        {/* A fan-out of five is six model conversations against one budget, and a
            reader who cannot see the split has no way to tell an expensive
            specialist from a cheap one. */}
        {delegation.costUsd !== null && (
          <span
            className="text-muted-foreground/60 shrink-0 font-mono text-[10px]"
            title={t("tokens", {
              input: delegation.inputTokens ?? 0,
              output: delegation.outputTokens ?? 0,
            })}
          >
            ${delegation.costUsd.toFixed(4)}
          </span>
        )}
        <ChevronDown
          className={cn(
            "text-muted-foreground/50 h-3 w-3 shrink-0 transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {open && (
        <div className="space-y-2 pb-2">
          {/* What it was asked, first: a delegation whose brief nobody can see is a
              black box that costs money. */}
          <p className="text-muted-foreground border-foreground/10 border-l pl-2.5 text-[12px] leading-relaxed">
            {delegation.prompt}
          </p>

          {delegation.thinking !== "" && (
            <pre className="text-muted-foreground border-foreground/10 max-h-40 overflow-y-auto border-l pl-2.5 text-[11px] leading-relaxed whitespace-pre-wrap">
              {delegation.thinking}
            </pre>
          )}

          {delegation.steps.length > 0 && (
            <div className="border-foreground/10 space-y-0.5 border-l pl-3.5">
              {delegation.steps.map((step) => {
                // The delegate's own tools - the only place a reader learns that the
                // researcher searched a collection the parent cannot even see. A
                // plain row rather than something openable, and that is the contract
                // rather than a rendering choice: the frames carry no arguments and
                // no result, so there is nothing behind a chevron. See
                // `DelegationStep`.
                const shown = toolStep(step.name, undefined, step.ok !== null, tTools);
                return (
                  <AgentStep
                    key={step.id}
                    label={shown.label}
                    detail={shown.detail}
                    kind={shown.kind}
                    state={step.ok === null ? "running" : step.ok ? "done" : "error"}
                    expanded={false}
                  />
                );
              })}
            </div>
          )}

          {delegation.text !== "" && (
            <div className="prose-sm max-w-none text-[13px] leading-relaxed">
              <MarkdownContent content={delegation.text} />
            </div>
          )}

          {delegation.error !== null && (
            <p className="text-destructive text-[12px] leading-relaxed">{delegation.error}</p>
          )}

          {/* The run this delegation produced, which is the only place its cost,
              its model and its tokens are recorded as its own rather than folded
              into the parent's. In the body rather than the header, because the
              header is a button and a link inside one is not a link.

              Absent for an inline specialist, which gets no run row at all - the
              same shape as an unlinked delegate in the approval queue, where a
              missing id means there is no page rather than a forgotten link. And
              absent for a caller without `runs:view`, who would land on a page
              the server refuses. */}
          {delegation.runId !== null && can(Perm.runsView) && (
            <Link
              href={`${ROUTES.RUNS}?run=${delegation.runId}`}
              className="text-muted-foreground hover:text-foreground inline-block text-[12px] underline underline-offset-4"
            >
              {t("openInRunHistory")}
            </Link>
          )}

          {/* A specialist the model invented is persisted nowhere, so keeping it is
              a decision that can only be made while the run is still on screen -
              this is that window. Shown only when the frame carried a definition (a
              dynamic specialist, not a delegate or inline one) and only to a caller
              who may create an agent, which is what promoting does. */}
          {delegation.specialist !== null && can(Perm.agentsEdit) && (
            <PromoteDynamicSpecialist
              name={delegation.subagent}
              definition={delegation.specialist}
            />
          )}

          {/* Nested under the work that produced them: a specialist delegates
              partway through, so its own delegates belong after what it had said by
              then rather than above it. */}
          {children.map((child) => (
            <DelegationPanel key={child.taskId} delegation={child} all={all} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Keep a specialist the model invented, by promoting it to a draft agent.
 *
 * Mounted only for a dynamic delegation whose definition the frame carried, so the
 * model-profile query runs for those panels alone rather than every one. The
 * specialist named its model by the label an author sees; a standalone agent is
 * keyed by the profile's id, so it is resolved here - and a label that no longer
 * resolves (a profile deleted since) promotes with no model, leaving the draft to
 * ask for one before it can publish rather than failing the promote.
 *
 * The name is the model's own - whatever it chose when it invented the specialist,
 * which the library allows but the backend `SpecialistSpec` may reject (its pattern
 * and length). A person cannot edit it in chat, so the control refuses up front
 * with the reason - the same disable the Builder's `SpecialistEditor` does on a
 * name it would fail to publish - rather than letting the promote 422 into a toast.
 */
function PromoteDynamicSpecialist({
  name,
  definition,
}: {
  name: string;
  definition: SpecialistDefinition;
}) {
  const t = useTranslations("chat.delegation");
  // The name-error copy lives with the Builder's, keyed off the same helper; a
  // second translator reaches it without duplicating the strings into `chat`.
  const tAgents = useTranslations("agents");
  const { profiles } = useModelProviders();
  const { promote } = useAgents();
  const nameError = specialistNameError(name);
  const modelProfileId = profiles.find((profile) => profile.label === definition.model)?.id ?? null;

  const onPromote = () =>
    promote.mutate(
      {
        specialist: {
          ...newSpecialist(),
          name,
          description: definition.description,
          instructions: definition.instructions,
          model_profile_id: modelProfileId,
        },
        // A dynamic specialist always names its own model, so there is no parent
        // model to fall back to.
        fallbackModelProfileId: null,
      },
      {
        onSuccess: (agent) => toast.success(t("specialistPromoted", { name: agent.name })),
        onError: (error) => toast.error(getErrorMessage(error)),
      },
    );

  return (
    <div>
      <Button
        variant="outline"
        size="sm"
        // A promoted specialist keeps its name as the new agent's handle, so a name
        // the backend would refuse cannot be promoted - the same guard the Builder
        // puts on its own promote button.
        disabled={promote.isPending || nameError !== null}
        onClick={onPromote}
      >
        <CopyPlus className="h-3.5 w-3.5" />
        {t("promoteSpecialist")}
      </Button>
      {nameError !== null ? (
        <p className="text-destructive mt-1 text-[12px] leading-relaxed">{tAgents(nameError)}</p>
      ) : (
        <p className="text-muted-foreground mt-1 text-[12px] leading-relaxed">
          {t("promoteSpecialistDetail")}
        </p>
      )}
    </div>
  );
}
