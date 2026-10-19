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
  const cost = `$${Number(usage.cost_usd).toFixed(4)}`;
  const tokens = { input: usage.input_tokens, output: usage.output_tokens };
  const detail = usage.cost_is_partial
    ? t("tokensDetailPartial", tokens)
    : t("tokensDetail", tokens);
  return (
    <span className="text-muted-foreground font-mono text-xs" title={withCache(t, detail, usage)}>
      ↓{usage.input_tokens.toLocaleString()} ↑{usage.output_tokens.toLocaleString()} ·{" "}
      {usage.cost_is_partial ? `≥ ${cost}` : cost}
    </span>
  );
}

/**
 * The detail line, with how much of the input the provider's cache served or
 * took (#2170) - priced at a fraction of the input rate and above it, so "998k
 * input" alone reads as 998k full-price tokens when most were cache reads.
 */
function withCache(t: ReturnType<typeof useTranslations>, detail: string, usage: TurnUsage) {
  const read = usage.cache_read_tokens ?? 0;
  const write = usage.cache_write_tokens ?? 0;
  if (read === 0 && write === 0) return detail;
  return t("tokensWithCache", { detail, read, write });
}

/** The smallest sum a rounded cost can name; anything under it is "< $0.01". */
const CENT = 0.01;

/**
 * What one answer cost, rounded to the cent, under that answer in the chat.
 *
 * A reader of a conversation wants to know whether an answer was expensive, which
 * "$0.01" says and "$0.0125" with its token counts said less readably; the exact
 * figure is the title, one hover away. A turn under a cent says so rather than
 * claiming it was free.
 */
export function RoundedCost({ usage }: MessageCostProps) {
  const t = useTranslations("chat");
  const exact = Number(usage.cost_usd);
  const rounded = exact > 0 && exact < CENT ? `< $${CENT.toFixed(2)}` : `$${exact.toFixed(2)}`;
  return (
    <span
      className="text-muted-foreground text-xs tabular-nums"
      title={withCache(
        t,
        usage.cost_is_partial
          ? t("exactCostPartial", { cost: `$${exact.toFixed(4)}` })
          : `$${exact.toFixed(4)}`,
        usage,
      )}
    >
      {usage.cost_is_partial ? `≥ ${rounded}` : rounded}
    </span>
  );
}
