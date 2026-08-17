import { useTranslations } from "next-intl";

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
 * Drawn on a live turn and on a stored one alike: the columns are on the message
 * row, so a reloaded conversation shows what each answer cost rather than nothing.
 * Absence still renders nothing at all rather than zeroes — a turn nobody could
 * measure is not a free one.
 *
 * **A partial cost says so.** When the run reached a model with no price entry the
 * ledger books that request at zero, so the figure is short by however much it
 * cost. It is prefixed with `≥` rather than dropped: a floor somebody can act on
 * beats silence, and a bare `$0.0042` under an answer whose real price is unknown
 * is the number that lies (#772).
 */
export function MessageCost({ usage }: MessageCostProps) {
  const t = useTranslations("chat");
  const cost = `$${usage.cost_usd.toFixed(4)}`;
  return (
    <span
      className="text-muted-foreground font-mono text-[10px]"
      title={
        usage.cost_is_partial
          ? t("tokensDetailPartial", {
              input: usage.input_tokens,
              output: usage.output_tokens,
            })
          : t("tokensDetail", { input: usage.input_tokens, output: usage.output_tokens })
      }
    >
      ↓{usage.input_tokens.toLocaleString()} ↑{usage.output_tokens.toLocaleString()} ·{" "}
      {usage.cost_is_partial ? `≥ ${cost}` : cost}
    </span>
  );
}
