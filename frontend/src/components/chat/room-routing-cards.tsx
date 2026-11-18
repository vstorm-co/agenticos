"use client";

import { useRef, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { Button, Checkbox } from "@/components/ui";
import { useRoomDecisionAttempt, useRoomRoutingActions } from "@/hooks/use-room-routing";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { clientId } from "@/lib/ids";
import { useAuthStore } from "@/stores";
import type {
  RoomAgentPin,
  RoomDecisionAttempt,
  RoomRoutingProposal,
  RoomTaskCard,
} from "@/types/room-routing";

function Ownership({
  accountable,
  name,
  agent,
  due,
}: {
  accountable: string | null;
  name?: string | null;
  agent: RoomAgentPin | null;
  due: string | null;
}) {
  const t = useTranslations("chat.roomRouting");
  const format = useFormatter();
  const me = useAuthStore((state) => state.user?.id);
  const timestamp = due === null ? NaN : Date.parse(due);
  return (
    <dl className="text-muted-foreground grid gap-1 text-xs">
      <div>
        <dt className="inline font-medium">{t("accountable")}: </dt>
        <dd className="inline">
          {accountable === me
            ? t("you")
            : name || t(accountable === null ? "unassigned" : "teammate")}
        </dd>
      </div>
      {agent && (
        <div>
          <dt className="inline font-medium">{t("specialist")}: </dt>
          <dd className="inline break-words">
            {agent.name}
            {!agent.current && <span> · {t("pinnedVersion")}</span>}
          </dd>
        </div>
      )}
      {Number.isFinite(timestamp) && (
        <div>
          <dt className="inline font-medium">{t("due")}: </dt>
          <dd className="inline">
            <time dateTime={due!} title={due!}>
              {format.dateTime(new Date(timestamp), { dateStyle: "medium", timeStyle: "short" })}
            </time>
          </dd>
        </div>
      )}
    </dl>
  );
}

export function RoomThreadLocation({
  root,
  onOpen,
}: {
  root: string | null;
  onOpen?: (root: string) => void;
}) {
  const t = useTranslations("chat.roomRouting");
  if (root === null) return null;
  return onOpen ? (
    <Button
      size="sm"
      variant="link"
      className="h-auto min-h-9 px-0 text-xs"
      onClick={() => onOpen(root)}
    >
      {t("openThread")}
    </Button>
  ) : (
    <p className="text-muted-foreground text-xs">{t("inThread")}</p>
  );
}

export function RoomProposalCard({
  proposal,
  readOnly,
  onOpenThread,
}: {
  proposal: RoomRoutingProposal;
  readOnly: boolean;
  onOpenThread?: (root: string) => void;
}) {
  const t = useTranslations("chat.roomRouting");
  const errors = useTranslations("errors");
  const actions = useRoomRoutingActions(proposal.conversation_id);
  const [selection, setSelection] = useState({ revision: proposal.revision, ids: [] as string[] });
  const [result, setResult] = useState<RoomRoutingProposal | null>(null);
  const savedAttempt = useRoomDecisionAttempt(proposal.conversation_id, proposal.id);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const busy = useRef(false);
  // Permission and redaction changes do not require a new proposal revision.
  const current = result && result.revision > proposal.revision ? result : proposal;
  const selected = selection.revision === current.revision ? selection.ids : [];
  const setSelected = (change: (ids: string[]) => string[]) =>
    setSelection((held) => ({
      revision: current.revision,
      ids: change(held.revision === current.revision ? held.ids : []),
    }));
  const attempt = current.decision === "pending" ? savedAttempt.attempt : null;
  const setAttempt = savedAttempt.set;
  const chosen = attempt?.input.selected_item_ids ?? selected;
  const canAccept = !readOnly && current.decision === "pending" && current.can_accept;
  const canDiscard = !readOnly && current.decision === "pending" && current.can_discard;
  const validSelection =
    selected.length > 0 &&
    selected.length <= 3 &&
    selected.every((id) => current.items.some((item) => item.proposal_item_id === id));
  async function decide(decision: "accept" | "discard") {
    if (
      busy.current ||
      readOnly ||
      (!attempt && (decision === "accept" ? !canAccept || !validSelection : !canDiscard))
    )
      return;
    busy.current = true;
    setPending(true);
    setFailure(null);
    const prior = savedAttempt.read();
    const held: RoomDecisionAttempt = prior ?? {
      decision,
      input: {
        expected_revision: current.revision,
        idempotency_key: clientId(),
        ...(decision === "accept" ? { selected_item_ids: [...selected] } : {}),
      },
    };
    setAttempt(held);
    let postingDecision = false;
    try {
      if (prior) {
        // A lost acknowledgement is read back before the same token may be replayed.
        const observed = await actions.readProposal(current.id);
        if (!observed) return;
        setResult(observed);
        if (observed.decision !== "pending") {
          setAttempt(null);
          actions.changed();
          return;
        }
        if (
          observed.revision !== held.input.expected_revision ||
          !(held.decision === "accept" ? observed.can_accept : observed.can_discard)
        ) {
          // A read cannot settle an earlier uncertain write. Keep its original token.
          setFailure(t("proposalChanged"));
          actions.changed();
          return;
        }
      }
      postingDecision = true;
      const accepted = await actions.decide(current.id, held.decision, held.input);
      if (accepted) {
        setResult(accepted);
        setAttempt(null);
        actions.changed();
      }
    } catch (error) {
      const refused = error instanceof ApiError && [400, 403, 404, 409, 422].includes(error.status);
      setFailure(
        postingDecision && error instanceof ApiError && error.status === 409
          ? t("proposalChanged")
          : getErrorMessage(error, errors, t("decisionFailed")),
      );
      if (refused) {
        // Access/validation may refuse a retry before reading the original decision.
        if (postingDecision && (prior === null || error.status === 409)) setAttempt(null);
        actions.changed();
      }
    } finally {
      busy.current = false;
      if (actions.isCurrent()) setPending(false);
    }
  }
  return (
    <article className="min-w-0 space-y-3 rounded-xl border p-3" aria-label={t("proposal")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t("proposal")}</h3>
        <span className="text-muted-foreground text-xs">{t(`decisions.${current.decision}`)}</span>
      </div>
      <RoomThreadLocation root={current.thread_root_message_id} onOpen={onOpenThread} />
      <p className="text-muted-foreground text-xs">{t("proposalHint")}</p>
      <ul className="space-y-3">
        {current.items.map((item) => (
          <li key={item.proposal_item_id} className="bg-muted/40 space-y-2 rounded-lg p-3">
            <label className="flex items-start gap-2">
              {current.decision === "pending" && canAccept && (
                <Checkbox
                  className="mt-0.5"
                  checked={chosen.includes(item.proposal_item_id)}
                  disabled={
                    pending ||
                    attempt !== null ||
                    (!selected.includes(item.proposal_item_id) && selected.length >= 3)
                  }
                  onCheckedChange={(checked) => {
                    setFailure(null);
                    setSelected((held) =>
                      checked === true
                        ? [...held, item.proposal_item_id]
                        : held.filter((id) => id !== item.proposal_item_id),
                    );
                  }}
                />
              )}
              <span className="min-w-0 text-sm font-medium break-words">{item.title}</span>
            </label>
            <p className="max-h-36 overflow-y-auto text-sm break-words whitespace-pre-wrap">
              {item.expected_result}
            </p>
            <Ownership
              accountable={item.accountable_user_id}
              name={item.accountable_user_name}
              agent={item.agent}
              due={item.due_at}
            />
            {item.existing_task_id !== null && (
              <p className="text-muted-foreground text-xs">{t("existingTask")}</p>
            )}
            {current.decision === "accepted" && (
              <p className="text-muted-foreground text-xs">
                {t(
                  current.accepted_item_ids.includes(item.proposal_item_id)
                    ? "itemAccepted"
                    : "itemNotAccepted",
                )}
              </p>
            )}
          </li>
        ))}
      </ul>
      {failure && (
        <p role="alert" className="text-destructive text-xs">
          {failure}
        </p>
      )}
      {attempt ? (
        <div className="space-y-2">
          {!pending && <p className="text-muted-foreground text-xs">{t("uncertainDecision")}</p>}
          <Button
            size="sm"
            variant="outline"
            disabled={pending || readOnly}
            onClick={() => void decide(attempt.decision)}
          >
            {t(pending ? "deciding" : "retryDecision")}
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {canAccept && (
            <Button
              size="sm"
              disabled={pending || !validSelection}
              onClick={() => void decide("accept")}
            >
              {t("acceptSelected")}
            </Button>
          )}
          {canDiscard && (
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() => void decide("discard")}
            >
              {t("discard")}
            </Button>
          )}
        </div>
      )}
      {current.decision === "pending" && !canAccept && !canDiscard && (
        <p className="text-muted-foreground text-xs">{t("requesterReview")}</p>
      )}
    </article>
  );
}

export function RoomCanonicalTaskCard({
  task,
  onOpenThread,
}: {
  task: RoomTaskCard;
  onOpenThread?: (root: string) => void;
}) {
  const t = useTranslations("chat.roomRouting");
  const me = useAuthStore((state) => state.user?.id);
  const locale = useLocale();
  return (
    <article className="min-w-0 space-y-2 rounded-xl border p-3" aria-label={t("task")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 text-sm font-semibold break-words">{task.title}</h3>
        <span className="bg-muted rounded-full px-2 py-1 text-xs font-medium">
          {t(`statuses.${task.status}`)}
        </span>
      </div>
      <RoomThreadLocation root={task.thread_root_message_id} onOpen={onOpenThread} />
      <p className="max-h-36 overflow-y-auto text-sm break-words whitespace-pre-wrap">
        {task.description}
      </p>
      <Ownership
        accountable={task.accountable_user_id}
        name={task.accountable_user_name}
        agent={task.agent}
        due={task.due_at}
      />
      <p className="text-sm">
        {t(
          task.next_actor === "agent"
            ? "nextAgent"
            : task.accountable_user_id === me
              ? "nextYou"
              : "nextPerson",
        )}
      </p>
      {task.status === "planned" &&
        task.next_actor === "user" &&
        task.accountable_user_id !== null &&
        task.accountable_user_id !== me && (
          <p className="text-muted-foreground text-xs">{t("teammateStarts")}</p>
        )}
      <Button asChild size="sm" variant="outline">
        <Link href={`/${locale}/tables/${task.table_id}`}>{t("openTaskBoard")}</Link>
      </Button>
    </article>
  );
}
