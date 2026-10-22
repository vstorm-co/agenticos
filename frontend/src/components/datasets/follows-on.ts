/** The question an answer replied to, as the chat that shows the answer sees it. */
export interface AskedBefore {
  question: string;
  /** Whether any turn came before the question, so there is a conversation to keep. */
  earlier: boolean;
}

// Openers that lean on an earlier turn, in the languages the console speaks.
const OPENERS =
  /^(and|but|also|so|then|what about|how about|it|its|it's|that|this|those|these|they|them|a co|a jak|i|oraz|to|ten|und|aber|was ist mit|das|es)([\s,.?!]|$)/;
const SHORT = 3;

/**
 * Whether a question probably needs the turns before it to make sense.
 *
 * A guess that only picks the default between keeping the conversation and
 * not: a short question, or one opening on "and", "what about" or a pronoun,
 * usually continues one ("And to Toronto?"), while a full question stands on its own.
 */
export function followsOn(question: string): boolean {
  const said = question.trim().toLowerCase();
  return said.split(/\s+/).filter(Boolean).length <= SHORT || OPENERS.test(said);
}
