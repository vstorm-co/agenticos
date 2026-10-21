"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";

import { BlobbyFace } from "@/components/desktop/blobby-face";
import { useBlobbyMotion } from "@/hooks/use-blobby-motion";
import { faceOf, pickLine, voiceOf } from "@/lib/desktop/blobby-cast";
import {
  ACTIVITY_SAY_MS,
  activityPath,
  expressionFor,
  HAPPY_MS,
  HOP_MS,
  NO_STROKE,
  SAY_MS,
  stroke,
  WAVE_MS,
  type Activity,
} from "@/lib/desktop/blobby-engine";
import {
  openChat,
  openInConsole,
  showBlobbyMenu,
  showConsole,
  type BlobbySettings,
} from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";
import { cn } from "@/lib/utils";

const DRAG_THRESHOLD = 4;
const DOUBLE_CLICK_MS = 350;
const FACE_SIZE = 112;

interface Bubble {
  text: string;
  /** A console page a click on the bubble opens, for a bubble about the agents. */
  path: string | null;
}

/** A line the shell asked blobby to say - a screenshot that could not be taken - numbered, so a repeat is said again. */
export interface Heard {
  text: string;
  id: number;
}

interface BlobbyProps {
  settings: BlobbySettings;
  activity: Activity;
  signedIn: boolean;
  heard: Heard | null;
  reducedMotion: boolean;
}

/**
 * Whether something keyed `key` is still within `ms` of first being shown.
 *
 * What blobby hears or notices arrives as props, and a bubble for it is derived
 * rather than copied into state: the only state is which key has run out, set
 * from a timer, never from the render or the effect body.
 */
function useFresh(key: string | null, ms: number): boolean {
  const [expired, setExpired] = useState<string | null>(null);
  useEffect(() => {
    if (key === null) return;
    const timer = setTimeout(() => setExpired(key), ms);
    return () => clearTimeout(timer);
  }, [key, ms]);
  return key !== null && expired !== key;
}

function run(what: string, command: () => Promise<void>) {
  command().catch((error: unknown) => reportShellFailure(what, error));
}

/**
 * Blobby, drawn: the creature, its speech bubble and the "New chat" button that
 * appears over its head on hover.
 *
 * Drag it anywhere; click it and it waves and says something; double-click it
 * and it hops and brings the console forward. Stroke it - the cursor back and
 * forth over it - and it is pleased. Right-click for the shell's menu. What the
 * agents are doing is said in the bubble, which opens the right page on click.
 */
export function Blobby({ settings, activity, signedIn, heard, reducedMotion }: BlobbyProps) {
  const t = useTranslations("desktop.blobby");
  const [quip, setQuip] = useState<Bubble | null>(null);
  const quipTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastLine = useRef<number | null>(null);
  const voice = voiceOf(settings.character);

  const say = useCallback((text: string) => {
    setQuip({ text, path: null });
    clearTimeout(quipTimer.current);
    quipTimer.current = setTimeout(() => setQuip(null), SAY_MS);
  }, []);

  const speak = useCallback(() => {
    lastLine.current = pickLine(Math.random, lastLine.current);
    say(t(`lines.${voice}.${lastLine.current}`));
  }, [say, t, voice]);

  const motion = useBlobbyMotion({
    roams: settings.roams,
    chatter: settings.chatter,
    still: reducedMotion || !signedIn,
    onQuip: speak,
  });

  useEffect(() => () => clearTimeout(quipTimer.current), []);

  // What the agents are doing, said for a while each time it changes; a click
  // on the bubble opens the page it is about.
  const noticed = settings.activity && activity.kind !== "quiet" ? activity : null;
  const noticeFresh = useFresh(noticed ? JSON.stringify(noticed) : null, ACTIVITY_SAY_MS);
  const heardFresh = useFresh(heard ? String(heard.id) : null, SAY_MS);
  const notice: Bubble | null =
    noticed && noticeFresh
      ? {
          text:
            noticed.kind === "approvals"
              ? t("approvals", { count: noticed.count })
              : noticed.kind === "unread"
                ? t("unread", { count: noticed.count })
                : t("running", { count: noticed.count }),
          path: activityPath(noticed),
        }
      : null;
  const bubble = quip ?? (heard && heardFresh ? { text: heard.text, path: null } : null) ?? notice;

  const pressed = useRef<{ x: number; y: number } | null>(null);
  // No click yet, rather than one at time zero: a page a third of a second old
  // would take its first click for the second of a double.
  const lastClick = useRef(Number.NEGATIVE_INFINITY);
  const stroking = useRef(NO_STROKE);

  const greet = () => {
    motion.react("wave", WAVE_MS);
    if (signedIn) speak();
    else say(t("signedOut"));
  };

  const onPointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return;
    pressed.current = { x: event.clientX, y: event.clientY };
  };

  const onPointerMove = (event: PointerEvent) => {
    const from = pressed.current;
    if (!from) {
      stroking.current = stroke(stroking.current, event.clientX, performance.now());
      if (stroking.current.pleased) {
        stroking.current = NO_STROKE;
        motion.react("happy", HAPPY_MS);
      }
      return;
    }
    if (Math.hypot(event.clientX - from.x, event.clientY - from.y) < DRAG_THRESHOLD) return;
    pressed.current = null;
    motion.startDragging();
  };

  const onPointerUp = () => {
    if (!pressed.current) return;
    pressed.current = null;
    const now = performance.now();
    if (now - lastClick.current < DOUBLE_CLICK_MS) {
      lastClick.current = Number.NEGATIVE_INFINITY;
      motion.react("hop", HOP_MS);
      run("could not bring the console forward", showConsole);
      return;
    }
    lastClick.current = now;
    greet();
  };

  const onBubble = () => {
    const path = bubble?.path;
    if (path) run("could not open the console", () => openInConsole(path));
  };

  const expression = signedIn ? expressionFor(motion.state, activity) : "sleepy";

  return (
    <div className="blobby group flex h-full flex-col items-center justify-end pb-2 select-none">
      <div role="status" className="relative h-16 w-full">
        {bubble ? (
          <button
            type="button"
            onClick={onBubble}
            className={cn(
              "blobby-bubble absolute inset-x-2 bottom-0 mx-auto w-fit max-w-full rounded-xl px-2.5 py-1.5 text-center text-xs leading-snug",
              bubble.path ? "cursor-pointer" : "cursor-default",
            )}
          >
            {bubble.text}
          </button>
        ) : signedIn ? (
          <button
            type="button"
            onClick={() => {
              motion.react("hop", HOP_MS);
              run("could not open a new chat", openChat);
            }}
            className="blobby-new-chat absolute inset-x-0 bottom-0 mx-auto flex w-fit items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          >
            <Plus className="size-3.5" aria-hidden />
            {t("newChat")}
          </button>
        ) : null}
      </div>
      {/* A button, so the keyboard can greet it too: Enter waves, as a click does. */}
      <button
        type="button"
        aria-label={t("label")}
        data-state={motion.state}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          pressed.current = null;
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            greet();
          }
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          run("could not open blobby's menu", showBlobbyMenu);
        }}
        className="blobby-body cursor-grab touch-none rounded-full outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] active:cursor-grabbing"
        style={{ scale: motion.state === "stroll" && motion.facing < 0 ? "-1 1" : undefined }}
      >
        <BlobbyFace
          face={faceOf(settings.character)}
          expression={expression}
          gaze={motion.gaze}
          size={FACE_SIZE}
        />
      </button>
    </div>
  );
}
