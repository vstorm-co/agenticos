"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";

import type { Mentionable, MentionKind } from "@/types/mention";

import { MentionMark } from "./mention-chip";

/** How long one example stays before the next one slides in. */
export const HINT_MS = 3800;

type Hint =
  | { kind: Exclude<MentionKind, "context">; item: Mentionable }
  | { kind: "slash"; command: string }
  | { kind: "mention" };

// The order the examples come in: what the agent can call, who it hands work
// to, what it can do and know - then the two keys that open it all up.
const KINDS: readonly Exclude<MentionKind, "context">[] = [
  "mcp",
  "capability",
  "agent",
  "skill",
  "collection",
];

// The capabilities that read well in "use … to work through the spreadsheet",
// best first; one that only asks or plans does not.
const WORKING_CAPABILITIES = [
  "sandbox",
  "code_execution",
  "web_research",
  "browser_use",
  "charts",
  "knowledge",
];

function example(offered: readonly Mentionable[], kind: Hint["kind"]): Mentionable | undefined {
  const ofKind = offered.filter((candidate) => candidate.kind === kind);
  if (kind !== "capability") return ofKind[0];
  return WORKING_CAPABILITIES.map((id) => ofKind.find((item) => item.id === id)).find(Boolean);
}

/** Examples drawn from what this agent really has, then `/` and `@` themselves. */
function hintsFor(offered: readonly Mentionable[], commands: readonly string[]): Hint[] {
  const hints: Hint[] = [{ kind: "mention" }];
  for (const kind of KINDS) {
    const item = example(offered, kind);
    if (item) hints.push({ kind, item });
  }
  const command = commands.find((name) => name === "summarize") ?? commands[0];
  if (command) hints.push({ kind: "slash", command });
  return hints;
}

function HintChip({ item }: { item: Mentionable }) {
  return (
    <span className="bg-foreground/[0.06] text-foreground/70 mx-px inline-flex items-center gap-1 rounded-md px-1.5 align-baseline text-[0.95em] leading-6 font-medium">
      <MentionMark item={item} className="h-4 w-4 text-[8px]" />
      {item.name}
    </span>
  );
}

/**
 * What the empty composer suggests, one example after another: a sentence with
 * this agent's own server, capability, delegate or skill in it as a chip, then
 * `/` and `@`. Each slides down out of the box as the next slides in from above.
 *
 * Decoration over the real placeholder, which stays the textbox's name: the
 * examples are hidden from assistive technology, and gone the moment the box
 * is focused or the conversation has a message in it.
 */
export function ComposerHints({
  offered,
  commands,
}: {
  offered: readonly Mentionable[];
  commands: readonly string[];
}) {
  const t = useTranslations("chat.hints");
  const hints = useMemo(() => hintsFor(offered, commands), [offered, commands]);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setShown((index) => index + 1), HINT_MS);
    return () => window.clearInterval(timer);
  }, []);

  const say = (hint: Hint) => {
    if (hint.kind === "mention") {
      return t.rich("mention", { key: (chunks) => <Key>{chunks}</Key> });
    }
    if (hint.kind === "slash") {
      return t.rich("slash", { command: () => <Key>{`/${hint.command}`}</Key> });
    }
    return t.rich(hint.kind, { chip: () => <HintChip item={hint.item} /> });
  };

  const current = hints[shown % hints.length]!;
  const previous = shown > 0 ? hints[(shown - 1) % hints.length]! : null;
  return (
    <div
      aria-hidden
      data-testid="composer-hints"
      className="text-muted-foreground pointer-events-none absolute inset-x-0 top-0 h-full overflow-hidden"
    >
      {previous && (
        <p
          key={`out-${shown}`}
          className="composer-hint-out absolute inset-x-0 top-0 truncate py-2.5"
        >
          {say(previous)}
        </p>
      )}
      <p key={`in-${shown}`} className="composer-hint-in truncate py-2.5">
        {say(current)}
      </p>
    </div>
  );
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <span className="bg-foreground/[0.06] text-foreground/70 mx-px rounded-md px-1.5 font-mono text-[0.9em]">
      {children}
    </span>
  );
}
