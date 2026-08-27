"use client";

import { BookOpen, FileText } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * What the agent found when it looked - the context files it may read, the skills
 * it may load.
 *
 * Both steps used to be `render: "none"`: a line saying the agent looked, with
 * nothing to open. The reasoning was that a prompt fragment is not something a
 * person reads, and it was wrong in the one case that matters - somebody asking
 * "does it actually see my glossary". The answer to that is the list, and the list
 * is right there in the result.
 */

interface Entry {
  name: string;
  description: string | null;
}

/** `- name: description`, or `- name` where the operator wrote no description. */
export function parseContextList(result: string): Entry[] | null {
  const entries: Entry[] = [];
  for (const line of result.split("\n")) {
    const match = /^\s*-\s+(\S[^:]*?)(?::\s*(.*\S))?\s*$/.exec(line);
    if (match === null || match[1] === undefined) continue;
    entries.push({ name: match[1], description: match[2] ?? null });
  }
  return entries.length > 0 ? entries : null;
}

/**
 * `list_skills` answers with a mapping of name to description.
 *
 * Reached as an object where the socket kept the shape, and as its JSON where
 * something stringified it on the way, so both are read. Anything else - an error
 * sentence, a mapping with nothing in it - is no list, and the step says so rather
 * than drawing an empty box.
 */
export function parseSkillList(result: unknown): Entry[] | null {
  const value = typeof result === "string" ? tryParse(result) : result;
  if (!isRecord(value)) return null;
  const entries = Object.entries(value).map(([name, description]) => ({
    name,
    description: typeof description === "string" && description !== "" ? description : null,
  }));
  return entries.length > 0 ? entries : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function tryParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** The context files this agent can read on demand. */
export function ContextListResult({ resultText }: { resultText: string }) {
  const t = useTranslations("chat.tools");
  return <EntryList entries={parseContextList(resultText)} kind="context" empty={t("noContext")} />;
}

/** The skills this agent can load. */
export function SkillListResult({ result }: { result: unknown }) {
  const t = useTranslations("chat.tools");
  return <EntryList entries={parseSkillList(result)} kind="skill" empty={t("noSkills")} />;
}

function EntryList({
  entries,
  kind,
  empty,
}: {
  entries: Entry[] | null;
  kind: "context" | "skill";
  empty: string;
}) {
  if (entries === null) {
    return <p className="text-muted-foreground py-2 text-xs italic">{empty}</p>;
  }
  const Icon = kind === "context" ? FileText : BookOpen;
  return (
    <ul className="max-h-72 scrollbar-thin space-y-1.5 overflow-y-auto py-1">
      {entries.map((entry) => (
        <li key={entry.name} className="flex items-start gap-2.5">
          <Icon className="text-muted-foreground/70 mt-[3px] h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0">
            <span className="text-foreground font-mono text-[12.5px]">{entry.name}</span>
            {entry.description !== null && (
              <span className="text-muted-foreground block text-[12.5px] leading-relaxed">
                {entry.description}
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
