"use client";

import { Bot, Mic } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { AvatarFace } from "@/components/ui/avatar-face";
import { cn } from "@/lib/utils";
import type { Caption } from "@/lib/voice/captions";
import { useAuthStore } from "@/stores";
import type { Agent } from "@/types/agents";

/** One turn on screen: its parts' words together, live until every part is final. */
interface LiveTurn {
  turnId: string;
  role: Caption["role"];
  text: string;
  live: boolean;
}

/** Consecutive parts of one turn become one message, the way the turn is saved. */
function turns(
  captions: readonly Caption[],
  hidden: ReadonlySet<string>,
  speaking: boolean,
): LiveTurn[] {
  const out: LiveTurn[] = [];
  for (const line of captions) {
    if (hidden.has(line.turnId)) continue;
    const last = out.at(-1);
    if (last?.turnId === line.turnId) {
      last.text = `${last.text} ${line.text}`;
      last.live ||= speaking && !line.final;
    } else {
      out.push({
        turnId: line.turnId,
        role: line.role,
        text: line.text,
        live: speaking && !line.final,
      });
    }
  }
  return out;
}

/** The words, each fading in as it arrives - the console's streaming text. */
function Words({ text }: { text: string }) {
  return (
    <>
      {text
        .split(/\s+/)
        .filter(Boolean)
        .map((word, index) => (
          <span key={index} className="stream-word">
            {index > 0 ? " " : ""}
            {word}
          </span>
        ))}
    </>
  );
}

function Meta({ live, user }: { live: boolean; user: boolean }) {
  const t = useTranslations("chat.voice.view");
  return (
    <div
      className={cn(
        "text-muted-foreground flex items-center gap-2.5 text-[11px]",
        user && "flex-row-reverse",
      )}
    >
      {live && (
        <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] tracking-wider uppercase">
          <span className="bg-destructive h-1.5 w-1.5 rounded-full motion-safe:animate-pulse" />
          {t("live")}
        </span>
      )}
      <span className="inline-flex items-center gap-1">
        <Mic className="h-3 w-3" aria-hidden />
        {t("voice")}
      </span>
    </div>
  );
}

/**
 * The call's turns while they are spoken (#54): each one an ordinary message at
 * the foot of the conversation, with the live caption inside it, until the saved
 * message takes its place (`hidden` holds the turns the transcript has). The
 * visible words change many times a second, so they are hidden from screen
 * readers; a polite live region announces each line once it is final.
 */
export function VoiceCaptions({
  captions,
  agentName,
  agent,
  hidden,
  speaking = true,
}: {
  captions: readonly Caption[];
  agentName: string;
  agent?: Agent;
  hidden: ReadonlySet<string>;
  /** Whether the call is still on; once it is over, nothing on screen is live. */
  speaking?: boolean;
}) {
  const t = useTranslations("chat.voice.captions");
  const user = useAuthStore((state) => state.user);
  const lastFinal = captions.findLast((line) => line.final);
  return (
    <div>
      <div data-testid="voice-captions-visible" aria-hidden="true">
        {turns(captions, hidden, speaking).map((turn) =>
          turn.role === "user" ? (
            <div key={turn.turnId} className="flex flex-row-reverse gap-2 py-3 sm:gap-4">
              <div className="bg-foreground text-background flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full sm:h-9 sm:w-9">
                {user && <AvatarFace seed={user.id} colorSlot={user.avatar_color} />}
              </div>
              <div className="flex max-w-[85%] flex-col items-end gap-1.5">
                <p
                  className={cn(
                    "bg-secondary rounded-2xl rounded-tr-sm border px-3.5 py-2 text-[14.5px] leading-relaxed break-words",
                    turn.live ? "border-foreground/30" : "border-border/60",
                  )}
                >
                  <Words text={turn.text} />
                </p>
                <Meta live={turn.live} user />
              </div>
            </div>
          ) : (
            <div key={turn.turnId} className="flex gap-2 py-3 sm:gap-4">
              <div className="bg-muted flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full sm:h-9 sm:w-9">
                {agent ? (
                  <AgentAvatar
                    agentId={agent.id}
                    slug={agent.slug}
                    hasAvatar={agent.has_avatar}
                    size="md"
                    thinking={turn.live}
                    className="h-full w-full border-0"
                  />
                ) : (
                  <Bot className="h-4 w-4" />
                )}
              </div>
              <div className="flex max-w-[85%] min-w-0 flex-col gap-1.5">
                <p className="text-muted-foreground font-mono text-[11px] tracking-wider uppercase">
                  {agentName}
                </p>
                <p
                  className={cn(
                    "text-[14.5px] leading-relaxed break-words",
                    turn.live && "voice-live-rule",
                  )}
                >
                  <Words text={turn.text} />
                </p>
                <Meta live={turn.live} user={false} />
              </div>
            </div>
          ),
        )}
      </div>
      <p role="status" aria-live="polite" className="sr-only">
        {lastFinal
          ? lastFinal.role === "user"
            ? t("you", { text: lastFinal.text })
            : t("agent", { agent: agentName, text: lastFinal.text })
          : null}
      </p>
    </div>
  );
}
