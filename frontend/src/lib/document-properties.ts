import { isMap, isScalar, parseDocument } from "yaml";
import { SYSTEM_COLUMN_KEYS } from "./table-system-columns";
import { markdownDocument } from "./markdown-document";

export const SYSTEM_DOCUMENT_PROPERTIES: ReadonlySet<string> = new Set(SYSTEM_COLUMN_KEYS);

/** Body edits retain even legacy or invalid YAML byte for byte. */
export function withDocumentBody(source: string, body: string): string {
  const parts = markdownDocument(source);
  return source.slice(0, source.length - parts.body.length) + body;
}

interface ParsedProperties {
  document: ReturnType<typeof parseDocument>;
  valid: boolean;
  fields: { key: string; value: string; editable: boolean }[];
}

export function documentProperties(source: string): ParsedProperties {
  const { frontmatter } = markdownDocument(source);
  const document = parseDocument(frontmatter ?? "", { uniqueKeys: true });
  const valid =
    document.errors.length === 0 && (document.contents === null || isMap(document.contents));
  const fields: { key: string; value: string; editable: boolean }[] = [];
  if (valid && isMap(document.contents)) {
    for (const pair of document.contents.items) {
      if (!isScalar(pair.key) || typeof pair.key.value !== "string") continue;
      const key = pair.key.value;
      if (SYSTEM_DOCUMENT_PROPERTIES.has(key)) continue;
      const scalar = isScalar(pair.value) ? pair.value : null;
      fields.push({
        key,
        value: scalar ? String(scalar.value ?? "") : "",
        editable: scalar !== null && typeof scalar.value === "string",
      });
    }
  }
  return { document, valid, fields };
}

/** Property changes serialize only the header; the Markdown body is untouched. */
export function withDocumentProperty(source: string, key: string, value: string | null): string {
  const { document, valid } = documentProperties(source);
  if (!valid || SYSTEM_DOCUMENT_PROPERTIES.has(key)) return source;
  if (value === null) document.delete(key);
  else document.set(key, value);
  return `---\n${document.toString()}---\n${markdownDocument(source).body}`;
}
