/** The question an answer replied to, as the chat that shows the answer sees it. */
export interface AskedBefore {
  question: string;
  /** Whether any turn came before the question, so there is a conversation to keep. */
  earlier: boolean;
}

// Only openers that cannot start a question of its own: a pronoun or "I" can.
const OPENERS = /^(and|what about|how about|a co|a jak|und|was ist mit)([\s,.?!]|$)/;

/**
 * Whether a question plainly continues the conversation before it ("And to
 * Toronto?"), which only picks the default between keeping that conversation
 * and not. Anything else is offered alone: copying turns nobody chose is the
 * costlier mistake.
 */
export function followsOn(question: string): boolean {
  return OPENERS.test(question.trim().toLowerCase());
}

/** Whether to ask about the conversation at all: not when nothing came before the question. */
export function asksAboutHistory(asked: AskedBefore | undefined): boolean {
  return asked === undefined || asked.earlier;
}

/** The conversation is kept by default only for a question known to continue it. */
export function keepsHistoryFirst(asked: AskedBefore | undefined): boolean {
  return asked !== undefined && asked.earlier && followsOn(asked.question);
}
