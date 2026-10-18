/**
 * A person's message cut into what the console draws differently: picked
 * `@`-mentions and web addresses, between runs of plain text.
 *
 * Pure, and shared by the composer's highlight and the transcript, so a link or
 * a mention is recognised the same way before and after it is sent.
 */

import type { Mentionable } from "@/types/mention";
import { mentionSegments } from "./mentions";

/** One run of a message: plain text, a picked mention's token, or an address. */
export interface RichSegment {
  text: string;
  item?: Mentionable;
  url?: string;
}

// An address starts at `http(s)://` and runs to whitespace; punctuation that ends
// a sentence or closes a bracket around it is not part of it.
const LINK = /https?:\/\/[^\s<>"]+/g;
const TRAILING = /[.,;:!?'")\]]+$/;

/** The addresses in a run of text, each with where it starts. */
export function linksIn(text: string): { start: number; url: string }[] {
  return [...text.matchAll(LINK)].map((match) => ({
    start: match.index,
    url: match[0].replace(TRAILING, ""),
  }));
}

/** The text cut at each picked mention, then each address in what is left. */
export function richSegments(text: string, mentions: readonly Mentionable[]): RichSegment[] {
  return mentionSegments(text, mentions).flatMap((segment): RichSegment[] => {
    if (segment.item) return [segment];
    const out: RichSegment[] = [];
    let cursor = 0;
    for (const link of linksIn(segment.text)) {
      if (link.start > cursor) out.push({ text: segment.text.slice(cursor, link.start) });
      out.push({ text: link.url, url: link.url });
      cursor = link.start + link.url.length;
    }
    if (cursor < segment.text.length) out.push({ text: segment.text.slice(cursor) });
    return out;
  });
}

/** An address as a person reads it: the host without `www.`, then the path. */
export function readableLink(url: string): { host: string; path: string } {
  try {
    const parsed = new URL(url);
    const path = `${parsed.pathname}${parsed.search}`.replace(/^\/$/, "");
    return { host: parsed.hostname.replace(/^www\./, ""), path };
  } catch {
    return { host: url, path: "" };
  }
}
