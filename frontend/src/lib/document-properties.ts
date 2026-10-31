import { markdownDocument } from "./markdown-document";

/** Preserve legacy headers on body edits; new properties belong to table columns. */
export function withDocumentBody(source: string, body: string): string {
  const parts = markdownDocument(source);
  return source.slice(0, source.length - parts.body.length) + body;
}
