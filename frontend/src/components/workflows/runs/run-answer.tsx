"use client";

import { useTranslations } from "next-intl";

import { JsonView } from "@/components/ui/json-view";

interface Source {
  filename: string;
  collection: string;
  page: number | null;
}

/** A run's output read as the Output step records it: `WorkflowOutputPayload`. */
interface Answer {
  text: string | null;
  structured: Record<string, unknown> | null;
  sources: Source[];
  files: number;
}

const ANSWER_KEYS = new Set(["text", "sources", "artifacts", "structured"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sourceOf(value: unknown): Source | null {
  if (!isRecord(value)) return null;
  const { filename, collection, page } = value;
  if (typeof filename !== "string" || typeof collection !== "string") return null;
  return { filename, collection, page: typeof page === "number" ? page : null };
}

/**
 * The output as an answer, or null when it is not one - an output recorded
 * before the Output step had this shape, or one written by hand - which is then
 * shown as the JSON it is.
 */
function answerOf(output: Record<string, unknown>): Answer | null {
  if (Object.keys(output).some((key) => !ANSWER_KEYS.has(key))) return null;
  const text = output["text"] ?? null;
  const structured = output["structured"] ?? null;
  const sources = listOf(output["sources"]);
  const artifacts = listOf(output["artifacts"]);
  if (text !== null && typeof text !== "string") return null;
  if (structured !== null && !isRecord(structured)) return null;
  if (sources === null || artifacts === null) return null;
  const read: Source[] = [];
  for (const source of sources.map(sourceOf)) {
    if (source === null) return null;
    read.push(source);
  }
  // An Output step that hands on a called workflow's answer as its structured
  // result, and nothing of its own, answers with that workflow's answer.
  const inner = structured === null ? null : answerOf(structured);
  if (inner !== null && text === null && read.length === 0 && artifacts.length === 0) {
    return inner;
  }
  return { text, structured, sources: read, files: artifacts.length };
}

/** An absent list is an empty one; anything else is not a list. */
function listOf(value: unknown): unknown[] | null {
  if (value === undefined) return [];
  return Array.isArray(value) ? (value as unknown[]) : null;
}

/**
 * What a run answered with: its text as text, its structured result, the
 * passages it drew on and how many files it made - rather than the envelope
 * they travel in, which stays one click away for whoever needs the JSON.
 */
export function RunAnswer({ output }: { output: Record<string, unknown> }) {
  const t = useTranslations("pages.workflows");
  const answer = answerOf(output);
  if (answer === null) return <JsonView value={output} />;

  const empty =
    answer.text === null &&
    answer.structured === null &&
    answer.sources.length === 0 &&
    answer.files === 0;
  return (
    <div className="space-y-3">
      {empty && <p className="text-muted-foreground text-sm">{t("runAnswerEmpty")}</p>}
      {answer.text !== null && (
        <p className="text-sm break-words whitespace-pre-wrap">{answer.text}</p>
      )}
      {answer.structured !== null && <JsonView value={answer.structured} />}
      {answer.sources.length > 0 && (
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs font-medium">
            {t("runAnswerSources", { count: answer.sources.length })}
          </p>
          <ul className="space-y-0.5">
            {answer.sources.map((source, index) => (
              <li key={index} className="text-muted-foreground truncate text-xs">
                {source.page === null
                  ? t("runAnswerSource", { file: source.filename, collection: source.collection })
                  : t("runAnswerSourcePage", {
                      file: source.filename,
                      collection: source.collection,
                      page: source.page,
                    })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {answer.files > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("runAnswerFiles", { count: answer.files })}
        </p>
      )}
      {!empty && (
        <details>
          <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-xs select-none">
            {t("runAnswerRaw")}
          </summary>
          <JsonView value={output} className="mt-2" />
        </details>
      )}
    </div>
  );
}
