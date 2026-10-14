"use client";

import { ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { toolEntry } from "@/lib/tool-catalog";
import type { PendingVoiceApproval } from "@/lib/voice/call-reducer";

/** A value as the tool will receive it: a scalar as written, anything else as JSON. */
function shown(value: unknown): string {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : JSON.stringify(value, null, 2);
}

/** The catalog's name for a tool where it has one, its id otherwise. */
function useToolName(tool: string): string {
  const tTools = useTranslations("chat.tools");
  const entry = toolEntry(tool);
  return entry?.displayNameKey === undefined ? tool : tTools(entry.displayNameKey);
}

/**
 * A gated tool, put to the person on the call (#54). The arguments come first
 * and in large type, beside what the caller was heard to say, because the
 * person approving is the only check on a mishearing ("Acme" heard as
 * "Ahmad"). Buttons only: a "yes" said aloud does not approve.
 */
export function VoiceApprovalCard({
  approval,
  now,
  canDecide,
  onDecide,
}: {
  approval: PendingVoiceApproval;
  now: number;
  canDecide: boolean;
  onDecide: (approve: boolean) => void;
}) {
  const t = useTranslations("chat.voice.approval");
  const titleId = useId();
  const name = useToolName(approval.tool);
  const left = Math.max(0, Math.ceil((approval.deadline - now) / 1000));
  return (
    <section role="alertdialog" aria-labelledby={titleId} className="panel rounded-2xl border p-4">
      <h3 id={titleId} className="flex items-center gap-2 text-sm font-semibold">
        <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
        {t("title", { tool: name })}
      </h3>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
        {Object.entries(approval.args).map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="text-muted-foreground font-mono text-xs leading-6">{key}</dt>
            <dd className="text-base font-semibold break-words whitespace-pre-wrap">
              {shown(value)}
            </dd>
          </div>
        ))}
      </dl>
      {approval.said && (
        <p className="text-muted-foreground mt-3 text-sm">
          {t.rich("youSaid", { said: approval.said, q: (chunks) => <q>{chunks}</q> })}
        </p>
      )}
      <div
        role="progressbar"
        aria-label={t("countdown")}
        aria-valuemin={0}
        aria-valuemax={approval.timeoutSeconds}
        aria-valuenow={left}
        className="bg-muted mt-3 h-1 overflow-hidden rounded-full"
      >
        <div
          className="bg-foreground h-full motion-safe:transition-[width]"
          style={{ width: `${Math.min(100, (left / approval.timeoutSeconds) * 100)}%` }}
        />
      </div>
      <p className="text-muted-foreground mt-1 text-xs">{t("deniedIn", { seconds: left })}</p>
      {canDecide && (
        <div className="mt-3 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onDecide(false)}>
            {t("deny")}
          </Button>
          <Button type="button" onClick={() => onDecide(true)}>
            {t("approve")}
          </Button>
        </div>
      )}
      <p className="text-muted-foreground mt-2 text-xs">{t("notByVoice")}</p>
    </section>
  );
}

/** A gated tool this caller cannot approve by voice: said plainly, with what it would have run. */
export function VoiceApprovalUnavailable({
  tool,
  args,
  onDismiss,
}: {
  tool: string;
  args: Record<string, unknown>;
  onDismiss: () => void;
}) {
  const t = useTranslations("chat.voice.approval");
  const name = useToolName(tool);
  return (
    <section role="alert" className="panel rounded-2xl border p-4 text-sm">
      <p>{t("unavailable", { tool: name })}</p>
      <pre className="bg-muted mt-2 max-h-40 overflow-auto rounded p-2 font-mono text-xs">
        {JSON.stringify(args, null, 2)}
      </pre>
      <div className="mt-2 flex justify-end">
        <Button type="button" variant="ghost" onClick={onDismiss}>
          {t("dismiss")}
        </Button>
      </div>
    </section>
  );
}
