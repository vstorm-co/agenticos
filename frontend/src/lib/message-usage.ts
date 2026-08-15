import type { ConversationMessage, TurnUsage } from "@/types";

/** The fields a cost is read from, on whichever shape the message arrived as. */
interface Measured {
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: string | null;
  cost_is_partial?: boolean | null;
  context_used_tokens?: number | null;
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
    // Null is "not recorded", which is every message written before the column
    // existed. Drawn like an exact figure, because that is what it was drawn as
    // before and nobody can say otherwise about it now - the caveat is a claim
    // too, and `true` is the only one this knows to be right.
    cost_is_partial: message.cost_is_partial === true,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
    // The token count survives a reload; the window it is a share of does not
    // belong to the answer at all - it belongs to whichever model runs next, and
    // that can be switched between turns. So the count is read back and the
    // denominator is resolved where the selection is known.
    context:
      message.context_used_tokens == null ? null : { used_tokens: message.context_used_tokens },
  };
}

/**
 * What the newest measured answer in this conversation cost.
 *
 * The strip under the input reported the last *live* turn, so reopening a
 * conversation showed nothing at all until somebody sent a new message — and
 * "what did this thread cost" is asked exactly then. Searched from the end
 * because the last message is not always an answer, and not always one that was
 * measured.
 *
 * **`conversationId` is required, and it is not a convenience.** The store keeps the
 * transcript it last loaded, so for the moment between clicking another conversation
 * and its messages arriving, this list belongs to the thread somebody just left —
 * and the strip sat there reporting its tokens and its money under the new one.
 * Nothing is the right answer for that moment; a number from another conversation is
 * not.
 */
export function latestUsage(
  messages: ConversationMessage[],
  conversationId: string | null,
): TurnUsage | null {
  if (conversationId === null) return null;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message === undefined || message.role !== "assistant") continue;
    if (message.conversation_id !== conversationId) continue;
    const usage = storedUsage(message);
    if (usage !== null) return usage;
  }
  return null;
}
