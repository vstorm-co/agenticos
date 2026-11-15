"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Checkbox,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import type {
  EvalCaseCreate,
  EvalCaseRead,
  EvalTryRead,
  ProposalRead,
} from "@/lib/failure-learning-api";
import { useEvalTry } from "@/hooks/use-failure-learning";

import { EvalCaseForm } from "./eval-case-form";
import { TryView } from "./try-view";

/**
 * The agent's eval cases, each with its latest try's verdict, and the try
 * runner: pick cases, say how many samples of each, and what new text to
 * try. Tries run synchronously in the request, so keep them small - one or
 * two cases, one sample - until background execution lands.
 */
export function EvalCasesPanel({
  agentId,
  cases,
  proposals,
  isLoading,
  error,
  ledgerEntryId,
  canEdit,
  onCreate,
  onDelete,
  onStartTry,
  onProposeFromTry,
  tryProposalId,
  onTryProposalChange,
}: {
  agentId: string;
  cases: EvalCaseRead[];
  proposals: ProposalRead[];
  isLoading: boolean;
  error: Error | null;
  ledgerEntryId: string | null;
  canEdit: boolean;
  onCreate: (input: EvalCaseCreate) => void;
  onDelete: (caseId: string) => void;
  onStartTry: (input: {
    case_ids: string[];
    proposal_id?: string | null;
    instructions_override?: string | null;
    samples?: number;
  }) => Promise<EvalTryRead>;
  onProposeFromTry: (tryId: string, newText: string) => void;
  /** The proposal the try runs, `"none"` for the text typed below. Owned by the tab. */
  tryProposalId: string;
  onTryProposalChange: (proposalId: string) => void;
}) {
  const t = useTranslations("failureLearning");
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [samples, setSamples] = useState(1);
  const [override, setOverride] = useState("");
  const [activeTryId, setActiveTryId] = useState<string | null>(null);
  const { try: activeTry } = useEvalTry(agentId, activeTryId);
  const shown =
    ledgerEntryId === null
      ? cases
      : cases.filter((entry) => entry.ledger_entry_id === ledgerEntryId);
  const draftProposals = proposals.filter((proposal) => proposal.status === "draft");
  // A proposal applied or rejected since it was picked is no longer tryable:
  // fall back to the typed text rather than send a proposal the server refuses.
  const pickedProposalId = draftProposals.some((proposal) => proposal.id === tryProposalId)
    ? tryProposalId
    : "none";

  if (isLoading) return <LoadingState variant="skeleton-list" />;
  if (error) return <ErrorState />;
  return (
    <div className="space-y-3">
      {shown.length === 0 && !creating && <EmptyState title={t("noCases")} />}
      {shown.map((entry) => (
        <Card key={entry.id}>
          <CardContent className="flex flex-wrap items-center gap-3 p-4">
            <Checkbox
              checked={selected.includes(entry.id)}
              onCheckedChange={(checked) =>
                setSelected((current) =>
                  checked === true
                    ? [...current, entry.id]
                    : current.filter((id) => id !== entry.id),
                )
              }
              aria-label={entry.name}
            />
            <div className="min-w-0 flex-1">
              <p className="font-medium break-words">{entry.name}</p>
              <p className="text-muted-foreground line-clamp-2 text-sm">{entry.input.message}</p>
            </div>
            {entry.latest_try && (
              <Badge variant={entry.latest_try.gate_passed === true ? "default" : "secondary"}>
                {entry.latest_try.status === "pending"
                  ? t("gatePending")
                  : entry.latest_try.gate_passed
                    ? t("gatePassed")
                    : t("gateFailed")}
              </Badge>
            )}
            {canEdit && (
              <Button type="button" size="sm" variant="outline" onClick={() => onDelete(entry.id)}>
                {t("deleteCase")}
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => setCreating(true)}>
            {t("newCase")}
          </Button>
          <Button
            type="button"
            disabled={selected.length === 0}
            onClick={async () => {
              const evaluation = await onStartTry({
                case_ids: selected,
                // A try names a proposal or an override, never both: the
                // server refuses a try carrying both.
                proposal_id: pickedProposalId === "none" ? null : pickedProposalId,
                instructions_override:
                  pickedProposalId === "none" && override.trim() !== "" ? override.trim() : null,
                samples,
              });
              setActiveTryId(evaluation.id);
            }}
          >
            {t("runTry")}
          </Button>
        </div>
      )}
      {canEdit && selected.length > 0 && (
        <div className="flex flex-wrap gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="try-samples">{t("trySamples")}</Label>
            <Input
              id="try-samples"
              type="number"
              min={1}
              max={5}
              value={samples}
              onChange={(event) => setSamples(Number(event.target.value))}
              className="w-20"
            />
          </div>
          {draftProposals.length > 0 && (
            <div className="space-y-1.5">
              <Label htmlFor="try-proposal">{t("tryProposalLabel")}</Label>
              <Select value={pickedProposalId} onValueChange={onTryProposalChange}>
                <SelectTrigger id="try-proposal" className="w-64">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("tryProposalNone")}</SelectItem>
                  {draftProposals.map((proposal) => (
                    <SelectItem key={proposal.id} value={proposal.id}>
                      {proposal.new_text.slice(0, 80)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="min-w-64 flex-1 space-y-1.5">
            <Label htmlFor="try-override">{t("newTextLabel")}</Label>
            <Textarea
              id="try-override"
              value={override}
              onChange={(event) => setOverride(event.target.value)}
              disabled={pickedProposalId !== "none"}
            />
          </div>
        </div>
      )}
      {creating && (
        <EvalCaseForm
          ledgerEntryId={ledgerEntryId}
          onSubmit={(input) => {
            onCreate(input);
            setCreating(false);
          }}
          onCancel={() => setCreating(false)}
        />
      )}
      {activeTry && (
        <>
          <TryView evaluation={activeTry} />
          {activeTry.gate_passed === true && canEdit && override.trim() !== "" && (
            <Button
              type="button"
              variant="outline"
              onClick={() => onProposeFromTry(activeTry.id, override.trim())}
            >
              {t("proposeFromTry")}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
