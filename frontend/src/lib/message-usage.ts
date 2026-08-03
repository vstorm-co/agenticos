import type { ConversationMessage, TurnUsage } from "@/types";

/** The fields a cost is read from, on whichever shape the message arrived as. */
interface Measured {
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: string | null;
}

/**
 * What a stored message says it cost, or `null` when it says nothing.
 *
 * The API records the split and the money per message, and absent means **not
 * recorded** rather than free: every message written before the columns existed
 * carries nothing, and so does a turn whose cost could not be read. So a message
 * missing either token count answers `null`, and the client draws nothing —
 * "0 tokens · $0.0000" under an answer that cost money is a worse lie than silence.
 *
 * The budget and workspace fields are deliberately absent from the result. Those
 * describe the state of an organization *now*, not what a turn cost then, and
 * showing last month's percentage-of-budget under an old message would be a number
 * that was never true.
 */
export function storedUsage(message: Measured): TurnUsage | null {
  if (message.input_tokens == null || message.output_tokens == null) return null;
  return {
    input_tokens: message.input_tokens,
    output_tokens: message.output_tokens,
    // A string from the API, because money is `Numeric` on the wire.
    cost_usd: message.cost_usd == null ? 0 : Number(message.cost_usd),
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
  };
}

/**
 * What the newest measured answer in a transcript cost.
 *
 * The strip under the input reported the last *live* turn, so reopening a
 * conversation showed nothing at all until somebody sent a new message — and
 * "what did this thread cost" is asked exactly then. Searched from the end
 * because the last message is not always an answer, and not always one that was
 * measured.
 */
export function latestUsage(messages: ConversationMessage[]): TurnUsage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message === undefined || message.role !== "assistant") continue;
    const usage = storedUsage(message);
    if (usage !== null) return usage;
  }
  return null;
}
