import type { VoiceSavedTurn, VoiceServerFrame } from "@/types/voice";

/** One line: a speech part of a turn, word by word until it is final. */
export interface Caption {
  /** The saved message's `turn_id`; every part of one agent response shares it. */
  turnId: string;
  part: number;
  role: "user" | "assistant";
  text: string;
  final: boolean;
}

/** How many lines a call view keeps; the conversation keeps the rest as messages. */
export const CAPTION_LIMIT = 40;

/** A line's identity: its turn and which part of it. */
export function captionKey(line: Pick<Caption, "turnId" | "part">): string {
  return `${line.turnId}:${line.part}`;
}

/**
 * One caption frame applied to its part's line: `delta` appends, `text`
 * replaces the line with the screened words so far (an agent with an output
 * guardrail, whose captions arrive a sentence at a time), `final` replaces it
 * and closes it. Captions for the agent may run ahead of its audio over WebRTC
 * (#54) - the text arrives before the voice finishes, and that is accepted.
 */
export function applyCaption(
  captions: readonly Caption[],
  frame: Extract<VoiceServerFrame, { type: "caption" }>,
): Caption[] {
  const at = captions.findIndex(
    (line) => line.turnId === frame.turn_id && line.part === frame.part,
  );
  const current = at === -1 ? null : captions[at];
  const isFinal = typeof frame.final === "string";
  if (current?.final && !isFinal) return [...captions];
  const text = isFinal
    ? (frame.final as string)
    : typeof frame.text === "string"
      ? frame.text
      : (current?.text ?? "") + (frame.delta ?? "");
  const next: Caption = {
    turnId: frame.turn_id,
    part: frame.part,
    role: frame.role,
    text,
    final: isFinal,
  };
  const lines =
    at === -1 ? [...captions, next] : captions.map((line, i) => (i === at ? next : line));
  return lines.slice(-CAPTION_LIMIT);
}

/**
 * A saved turn takes the place of its caption lines: one final line with what
 * the conversation now holds - trimmed where the agent was talked over - where
 * the first of its parts stood. A turn with no caption on screen changes nothing.
 */
export function applySavedTurn(captions: readonly Caption[], message: VoiceSavedTurn): Caption[] {
  const at = captions.findIndex((line) => line.turnId === message.turn_id);
  if (at === -1) return [...captions];
  const first = captions[at] as Caption;
  const kept = captions.filter((line) => line.turnId !== message.turn_id);
  if (message.content === "") return kept;
  kept.splice(at, 0, { ...first, text: message.content, final: true });
  return kept;
}
