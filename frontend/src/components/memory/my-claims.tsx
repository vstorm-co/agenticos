"use client";

import { useState } from "react";
import { Pencil, Undo2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Badge, Button, Input, Textarea } from "@/components/ui";
import { useMyClaims } from "@/hooks/use-my-claims";
import type { MemoryClaim } from "@/lib/memory-api";

/**
 * What is on record about you - facts, preferences and decisions - with where each
 * came from, and the two things you may do about it.
 *
 * Correct replaces a claim with your own words and keeps the old one in the
 * history: "from Monday, Piotr takes over invoices" does not erase that Anna did
 * them before. Retract takes a claim out of use without deleting anything it came
 * from. Both are yours alone: a claim shared into a project or the organization is
 * a copy, and correcting yours does not rewrite theirs.
 */
export function MyClaims() {
  const t = useTranslations("pages.memory.claims");
  const format = useFormatter();
  const { page, isLoading, error, history, setHistory, correct, retract } = useMyClaims();
  const [editing, setEditing] = useState<string | null>(null);

  if (isLoading || error || !page) return null;
  if (page.items.length === 0 && !history) return null;

  return (
    <section className="space-y-3" data-tour="my-claims">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium">{t("title")}</h3>
          <p className="text-muted-foreground text-xs">{t("description")}</p>
        </div>
        <label className="text-muted-foreground flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={history}
            onChange={(event) => setHistory(event.target.checked)}
          />
          {t("showHistory")}
        </label>
      </div>
      <ul className="divide-y rounded-lg border">
        {page.items.map((claim) => (
          <li key={claim.id} className="space-y-2 px-4 py-3">
            {editing === claim.id ? (
              <ClaimEditor
                claim={claim}
                onCancel={() => setEditing(null)}
                onSave={async (statement, from) => {
                  await correct(claim.id, statement, from);
                  setEditing(null);
                }}
              />
            ) : (
              <ClaimRow
                claim={claim}
                since={
                  claim.effective_from
                    ? format.dateTime(new Date(claim.effective_from), { dateStyle: "medium" })
                    : null
                }
                onEdit={() => setEditing(claim.id)}
                onRetract={() => retract(claim.id)}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ClaimRow({
  claim,
  since,
  onEdit,
  onRetract,
}: {
  claim: MemoryClaim;
  since: string | null;
  onEdit: () => void;
  onRetract: () => void;
}) {
  const t = useTranslations("pages.memory.claims");
  const live = claim.status === "current" || claim.status === "disputed";
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <p className={live ? "text-sm" : "text-muted-foreground text-sm line-through"}>
          {claim.statement}
        </p>
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <span>
            {claim.scope === "profile"
              ? t("scopeProfile")
              : t("scopeAgent", { agent: claim.agent_name ?? t("anAgent") })}
          </span>
          <span>{t(`origin.${claim.origin}`)}</span>
          {claim.origin === "consolidation" ? (
            <span>{t("drawnFrom", { count: claim.derived_from_count })}</span>
          ) : null}
          {since ? <span>{t("since", { when: since })}</span> : null}
          {claim.status !== "current" ? (
            <Badge variant="outline">{t(`status.${claim.status}`)}</Badge>
          ) : null}
        </div>
      </div>
      {live ? (
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="sm" onClick={onEdit} aria-label={t("correct")}>
            <Pencil className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onRetract} aria-label={t("retract")}>
            <Undo2 className="h-4 w-4" />
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ClaimEditor({
  claim,
  onCancel,
  onSave,
}: {
  claim: MemoryClaim;
  onCancel: () => void;
  onSave: (statement: string, effectiveFrom: string | null) => Promise<void>;
}) {
  const t = useTranslations("pages.memory.claims");
  const [statement, setStatement] = useState(claim.statement);
  const [from, setFrom] = useState("");
  const changed = statement.trim() !== "" && statement.trim() !== claim.statement;
  return (
    <div className="space-y-2">
      <Textarea
        value={statement}
        maxLength={600}
        onChange={(event) => setStatement(event.target.value)}
        aria-label={t("statement")}
      />
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-muted-foreground flex items-center gap-2 text-xs">
          {t("effectiveFrom")}
          <Input type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
        </label>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            disabled={!changed}
            onClick={() => onSave(statement.trim(), from ? `${from}T00:00:00Z` : null)}
          >
            {t("save")}
          </Button>
        </div>
      </div>
    </div>
  );
}
