"use client";

import { Check, Clock, Lock, MessageSquare, Mic, ShieldAlert, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { toolDisplayName } from "@/lib/agent-step-captions";
import { cn } from "@/lib/utils";
import type { PendingVoiceApproval, SettledVoiceApproval } from "@/lib/voice/call-reducer";
import { clock } from "@/lib/voice/clock";

/** A value as the tool will receive it: a scalar as written, anything else as JSON. */
function shown(value: unknown): string {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : JSON.stringify(value, null, 2);
}

/** The tool by name and by id - the id is what runs. */
function ToolLine({ tool }: { tool: string }) {
  const tTools = useTranslations("chat.tools");
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <b className="text-base font-semibold tracking-tight">{toolDisplayName(tool, tTools)}</b>
      <code className="bg-muted rounded px-1.5 font-mono text-xs">{tool}</code>
    </div>
  );
}

/** The exact arguments, one row each; large while they wait on a decision. */
function Arguments({ args, large }: { args: Record<string, unknown>; large: boolean }) {
  return (
    <dl className="divide-border divide-y overflow-hidden rounded-[10px] border">
      {Object.entries(args).map(([key, value]) => (
        <div
          key={key}
          className="grid grid-cols-[minmax(92px,auto)_minmax(0,1fr)] items-baseline gap-3 px-3 py-2"
        >
          <dt className="text-muted-foreground font-mono text-xs">{key}</dt>
          <dd
            className={cn(
              "min-w-0 [overflow-wrap:anywhere] whitespace-pre-wrap",
              typeof value === "number" ? "font-mono" : "tracking-tight",
              large ? "text-[17px] font-semibold" : "text-sm font-medium",
            )}
          >
            {shown(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** What the caller was heard to say, beside what the tool would get. */
function Said({ said, warn }: { said: string; warn: boolean }) {
  const t = useTranslations("chat.voice.approval");
  return (
    <div className="text-muted-foreground grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[12.5px]">
      <Mic className="mt-0.5 h-3.5 w-3.5" aria-hidden />
      <span>
        {t.rich("youSaid", {
          said,
          q: (chunks: ReactNode) => <q className="text-foreground italic">{chunks}</q>,
        })}
      </span>
      {warn && <span className="col-start-2">{t("misheard")}</span>}
    </div>
  );
}

const CARD = "bg-card flex w-full max-w-[460px] flex-col gap-2.5 rounded-[14px] border p-3.5";

/**
 * A gated tool, put to the person on the call (#54). The arguments come first
 * and in large type, beside what the caller was heard to say, because the
 * person approving is the only check on a mishearing ("Acme" heard as
 * "Ahmad"). Buttons only: a "yes" said aloud does not approve. It brings itself
 * into view when it appears, and the call bar's strip points back to it.
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
  const tTools = useTranslations("chat.tools");
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [approval.id]);
  const left = Math.max(0, Math.ceil((approval.deadline - now) / 1000));
  return (
    <section
      ref={ref}
      role="group"
      aria-label={t("title", { tool: toolDisplayName(approval.tool, tTools) })}
      data-voice-approval
      className={cn(
        CARD,
        "border-warning/60 shadow-[0_0_0_3px_color-mix(in_oklch,var(--color-warning)_16%,transparent),0_8px_30px_-12px_rgb(0_0_0/0.25)]",
      )}
    >
      <div className="flex items-center gap-2 text-[13px] font-semibold">
        <ShieldAlert className="text-warning h-4 w-4 shrink-0" aria-hidden />
        <span>{t("needed")}</span>
        <span className="text-muted-foreground ml-auto font-mono text-xs font-medium whitespace-nowrap tabular-nums">
          {t("autoDeny", { time: clock(left) })}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={t("countdown")}
        aria-valuemin={0}
        aria-valuemax={approval.timeoutSeconds}
        aria-valuenow={left}
        className="bg-muted -mt-1 h-[3px] overflow-hidden rounded-full"
      >
        <div
          className="bg-warning h-full motion-safe:transition-[width] motion-safe:duration-1000 motion-safe:ease-linear"
          style={{
            width: `${approval.timeoutSeconds > 0 ? Math.min(100, (left / approval.timeoutSeconds) * 100) : 0}%`,
          }}
        />
      </div>
      <ToolLine tool={approval.tool} />
      <Arguments args={approval.args} large />
      {approval.said && <Said said={approval.said} warn />}
      <details>
        <summary className="text-muted-foreground w-fit cursor-pointer text-xs">
          {t("exactJson")}
        </summary>
        <pre className="bg-muted mt-1.5 overflow-x-auto rounded-lg px-2.5 py-2 font-mono text-xs">
          {JSON.stringify(approval.args, null, 2)}
        </pre>
      </details>
      {canDecide && (
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            className="min-w-[104px]"
            onClick={() => onDecide(false)}
          >
            <X aria-hidden />
            {t("deny")}
          </Button>
          <Button
            type="button"
            className="min-w-[104px]"
            data-voice-approve
            onClick={() => onDecide(true)}
          >
            <Check aria-hidden />
            {t("approve")}
          </Button>
        </div>
      )}
      {canDecide && <p className="text-muted-foreground text-[11.5px]">{t("notByVoice")}</p>}
    </section>
  );
}

/** How a decided approval reads afterwards: who decided, or that nobody did in time. */
export function VoiceApprovalSettled({ settled }: { settled: SettledVoiceApproval }) {
  const t = useTranslations("chat.voice.approval");
  const { approval, outcome } = settled;
  return (
    <section
      role="group"
      aria-label={t(`outcome.${outcome}`, { seconds: approval.timeoutSeconds })}
      className={CARD}
    >
      <p
        className={cn(
          "flex items-center gap-1.5 text-[12.5px] font-medium [&_svg]:h-3.5 [&_svg]:w-3.5",
          outcome === "approved" ? "[&_svg]:text-success" : "[&_svg]:text-destructive",
        )}
      >
        {outcome === "approved" ? (
          <Check aria-hidden />
        ) : outcome === "denied" ? (
          <X aria-hidden />
        ) : (
          <Clock aria-hidden />
        )}
        {t(`outcome.${outcome}`, { seconds: approval.timeoutSeconds })}
      </p>
      <ToolLine tool={approval.tool} />
      <Arguments args={approval.args} large={false} />
      {approval.said && <Said said={approval.said} warn={false} />}
    </section>
  );
}

/**
 * A gated tool this caller cannot approve by voice (#54): not hidden - said
 * plainly, with what it would have run, and where the request can wait for an
 * approver instead.
 */
export function VoiceApprovalUnavailable({
  tool,
  args,
  onDismiss,
  onEndCall,
}: {
  tool: string;
  args: Record<string, unknown>;
  onDismiss: () => void;
  onEndCall: () => void;
}) {
  const t = useTranslations("chat.voice.approval");
  const tTools = useTranslations("chat.tools");
  return (
    <section
      role="group"
      aria-label={t("unavailableTitle")}
      className={cn(CARD, "border-input border-dashed")}
    >
      <p className="flex items-center gap-2 text-[13px] font-semibold">
        <Lock className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
        {t("unavailableTitle")}
      </p>
      <ToolLine tool={tool} />
      <Arguments args={args} large={false} />
      <p className="text-muted-foreground text-[13px]">
        {t("unavailable", { tool: toolDisplayName(tool, tTools) })}
      </p>
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onDismiss}>
          {t("keepTalking")}
        </Button>
        <Button type="button" size="sm" onClick={onEndCall}>
          <MessageSquare aria-hidden />
          {t("continueInText")}
        </Button>
      </div>
    </section>
  );
}
