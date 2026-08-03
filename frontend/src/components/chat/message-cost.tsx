import type { TurnUsage } from "@/types";

interface MessageCostProps {
  usage: TurnUsage;
}

/**
 * What one answer cost, under that answer.
 *
 * Split rather than totalled, because input and output are priced an order of
 * magnitude apart: a turn that cost more than the one before it is either a long
 * answer or a long context, and the total cannot say which. The arrows carry that
 * distinction in the width of six characters — the alternative was two labelled
 * numbers under every message, which is a lot of furniture for a transcript.
 *
 * Only ever present on a live turn: usage is measured when a run finishes and is
 * not stored per message, so a reloaded conversation shows nothing here. That is
 * why absence renders nothing at all rather than zeroes.
 */
export function MessageCost({ usage }: MessageCostProps) {
  return (
    <span
      className="text-muted-foreground font-mono text-[10px]"
      title={`${usage.input_tokens.toLocaleString()} input · ${usage.output_tokens.toLocaleString()} output tokens`}
    >
      ↓{usage.input_tokens.toLocaleString()} ↑{usage.output_tokens.toLocaleString()} · $
      {usage.cost_usd.toFixed(4)}
    </span>
  );
}
