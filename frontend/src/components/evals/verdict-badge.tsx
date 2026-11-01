import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, MinusCircle, XCircle, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { ScorerStatus } from "@/types/scoring";

export type VerdictTone = "pass" | "fail" | "undecided" | "error";

const TONE: Record<
  VerdictTone,
  { variant: "success" | "destructive" | "secondary" | "warning"; icon: LucideIcon; color: string }
> = {
  pass: { variant: "success", icon: CheckCircle2, color: "text-success" },
  fail: { variant: "destructive", icon: XCircle, color: "text-destructive" },
  undecided: { variant: "secondary", icon: MinusCircle, color: "text-muted-foreground" },
  error: { variant: "warning", icon: AlertTriangle, color: "text-warning" },
};

export const SCORER_TONE: Record<ScorerStatus, VerdictTone> = {
  pass: "pass",
  fail: "fail",
  skipped: "undecided",
  error: "error",
};

/** A pass/fail/undecided answer as an icon in its colour; the caller adds the words. */
export function VerdictIcon({ tone, className }: { tone: VerdictTone; className?: string }) {
  const { icon: Icon, color } = TONE[tone];
  return <Icon className={cn("h-4 w-4 shrink-0", color, className)} aria-hidden />;
}

/**
 * A verdict as one pill: the tone's tint, its icon in colour and the words, so
 * the status never rests on colour alone.
 */
export function VerdictBadge({
  tone,
  title,
  className,
  children,
}: {
  tone: VerdictTone;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Badge variant={TONE[tone].variant} title={title} className={className}>
      <VerdictIcon tone={tone} className="h-3.5 w-3.5" />
      {children}
    </Badge>
  );
}
