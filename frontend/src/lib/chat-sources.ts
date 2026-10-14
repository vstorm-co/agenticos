import { parseRAGResults } from "@/components/chat/tool-results/rag";
import { parseWebSearch } from "@/components/chat/tool-results/web-search";
import type { Translate } from "@/lib/agent-step-captions";
import { hostOf } from "@/lib/link-brands";
import type { ChatMessage, ToolCall } from "@/types";

export interface SourceItem {
  index: number;
  type: "rag" | "web";
  title: string;
  subtitle?: string;
  url?: string;
  content?: string;
  score?: number;
  /** The collection a knowledge base passage came from, which names its base. */
  collection?: string;
}

function getToolCalls(message: ChatMessage): ToolCall[] {
  const fromParts = (message.parts ?? [])
    .filter((p) => p.type === "tool" && !!p.toolCall)
    .map((p) => p.toolCall!);
  if (fromParts.length > 0) return fromParts;
  return message.toolCalls ?? [];
}

export function extractSources(message: ChatMessage, t: Translate): SourceItem[] {
  const sources: SourceItem[] = [];
  // An agent that searches twice is often handed the same passage twice, and a
  // reader counting sources counts it once.
  const seen = new Set<string>();
  const fresh = (source: SourceItem): boolean => {
    const identity = `${sourceKey(source)}\n${source.content ?? ""}`;
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  };

  for (const tc of getToolCalls(message)) {
    const result = typeof tc.result === "string" ? tc.result : "";
    if (!result) continue;

    if (tc.name === "search_documents") {
      for (const item of parseRAGResults(result)) {
        const source: SourceItem = {
          index: item.index,
          type: "rag",
          title: item.source,
          subtitle:
            [item.page && `p.${item.page}`, item.chunk && t("chunkNumber", { number: item.chunk })]
              .filter(Boolean)
              .join(" · ") || undefined,
          content: item.content,
          score: item.score ? parseFloat(item.score) : undefined,
          collection: item.collection,
        };
        if (fresh(source)) sources.push(source);
      }
    } else if (tc.name === "web_search") {
      const payload = parseWebSearch(result);
      if (payload?.results) {
        payload.results.forEach((hit, i) => {
          const source: SourceItem = {
            index: i + 1,
            type: "web",
            title: hit.title || (hostOf(hit.url) ?? hit.url),
            subtitle: hostOf(hit.url) ?? hit.url,
            url: hit.url,
            content: hit.content,
          };
          if (fresh(source)) sources.push(source);
        });
      }
    }
  }

  return sources;
}

/** One document an answer drew on: every passage of a file, or one web page. */
export interface SourceDocument {
  key: string;
  type: SourceItem["type"];
  title: string;
  /** The page's address, for a web source. */
  url?: string;
  collection?: string;
  /** The first passage's index, which the panel opens on. */
  index: number;
  passages: number;
}

/** Which document a source belongs to: a file in a collection, or a page. */
export function sourceKey(source: SourceItem): string {
  return source.type === "rag"
    ? `rag:${source.collection ?? ""}:${source.title}`
    : `web:${source.url ?? source.title}`;
}

/**
 * The documents behind an answer's sources, in the order they were first cited.
 *
 * A search returns passages, and five passages of one handbook are one source to
 * the person reading - the stack under the answer counts files and pages, not
 * chunks.
 */
export function sourceDocuments(sources: SourceItem[]): SourceDocument[] {
  const documents = new Map<string, SourceDocument>();
  for (const source of sources) {
    const key = sourceKey(source);
    const known = documents.get(key);
    if (known) {
      known.passages += 1;
      continue;
    }
    documents.set(key, {
      key,
      type: source.type,
      title: source.title,
      url: source.url,
      collection: source.collection,
      index: source.index,
      passages: 1,
    });
  }
  return [...documents.values()];
}
