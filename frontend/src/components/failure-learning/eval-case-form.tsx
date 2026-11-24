"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useRunTranscript } from "@/hooks/use-runs";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import type { EvalCaseCreate, EvalExpectation } from "@/lib/failure-learning-api";

/** The API's cap on a case input: a transcript turn longer than this is cut. */
const MAX_INPUT_CHARS = 20000;

/** The expectation kinds, shown verbatim: they are API enum values, not copy. */
const EXPECTATION_KINDS: EvalExpectation["kind"][] = ["equals", "contains", "not_contains"];

/**
 * A case, pre-filled from the run that showed the failure: the run's last
 * user message is the failing part, and the turns before it are the history
 * the case replays. The curator edits the message down and writes what the
 * answer should say - only a person knows which part of the bad experience
 * is the failure.
 */
export function EvalCaseForm({
  ledgerEntryId,
  onSubmit,
  onCancel,
}: {
  ledgerEntryId: string | null;
  onSubmit: (input: EvalCaseCreate) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("failureLearning");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [kind, setKind] = useState<EvalExpectation["kind"]>("contains");
  const [field, setField] = useState<EvalExpectation["field"]>("text");
  const [value, setValue] = useState("");
  const [sourceRunId, setSourceRunId] = useState("");
  const { transcript } = useRunTranscript(sourceRunId, "conversation", {
    enabled: sourceRunId !== "",
  });

  const loadFromRun = () => {
    const turns = (transcript?.items ?? []).filter(
      (turn) => turn.role === "user" || turn.role === "assistant",
    );
    const lastUserAt = turns.map((turn) => turn.role).lastIndexOf("user");
    if (lastUserAt < 0) return;
    setMessage(turns[lastUserAt]?.content.slice(0, MAX_INPUT_CHARS) ?? "");
    setHistory(
      turns.slice(Math.max(0, lastUserAt - 10), lastUserAt).map((turn) => ({
        role: turn.role as "user" | "assistant",
        text: turn.content.slice(0, MAX_INPUT_CHARS),
      })),
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("newCase")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({
              ledger_entry_id: ledgerEntryId,
              name: name.trim(),
              input: { message: message.trim(), history },
              expectation: { kind, field, value: value.trim() },
              source_run_id: sourceRunId.trim() === "" ? null : sourceRunId.trim(),
            });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="case-name">{t("caseNameLabel")}</Label>
            <Input
              id="case-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="case-run">{t("caseSourceRunLabel")}</Label>
            <div className="flex gap-2">
              <Input
                id="case-run"
                value={sourceRunId}
                onChange={(event) => setSourceRunId(event.target.value)}
                placeholder={t("caseSourceRunPlaceholder")}
              />
              <Button
                type="button"
                variant="outline"
                onClick={loadFromRun}
                disabled={sourceRunId.trim() === ""}
              >
                {t("loadFromRun")}
              </Button>
            </div>
            <p className="text-muted-foreground text-sm">{t("loadFromRunHint")}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="case-message">{t("caseMessageLabel")}</Label>
            <Textarea
              id="case-message"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={t("caseMessagePlaceholder")}
              required
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div className="space-y-1.5">
              <Label htmlFor="case-kind">{t("caseExpectationKind")}</Label>
              <Select
                value={kind}
                onValueChange={(next) => setKind(next as EvalExpectation["kind"])}
              >
                <SelectTrigger id="case-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXPECTATION_KINDS.map((expectationKind) => (
                    <SelectItem key={expectationKind} value={expectationKind}>
                      {expectationKind}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="case-field">{t("caseExpectationField")}</Label>
              <Select
                value={field}
                onValueChange={(next) => setField(next as EvalExpectation["field"])}
              >
                <SelectTrigger id="case-field">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="text">{t("caseExpectationText")}</SelectItem>
                  <SelectItem value="status">{t("caseExpectationStatus")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="case-value">{t("caseExpectationValue")}</Label>
              <Input
                id="case-value"
                value={value}
                onChange={(event) => setValue(event.target.value)}
                required
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={name.trim() === "" || message.trim() === "" || value.trim() === ""}
            >
              {t("create")}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("cancel")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
