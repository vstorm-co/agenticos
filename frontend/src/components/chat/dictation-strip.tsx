"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { CircleAlert, Info, Lock, Mic, MicOff, TriangleAlert, type LucideIcon } from "lucide-react";
import type { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { DictationActions, DictationState } from "@/hooks/use-dictation";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";

import { clock } from "./dictation-bar";

/** One hint, prompt or error under the composer. */
export interface StripHint {
  /** Which hint this is: a new key cross-fades the text inside an open strip. */
  key: string;
  tone: "hint" | "warn" | "error";
  icon: LucideIcon;
  /** The whole message, emphasis and links included. It wraps; it is never cut. */
  message: ReactNode;
  actions?: ReactNode;
}

/** Why the crossed-out microphone is crossed out, when somebody asked. */
export type DictationUnavailable = "not_ready" | "no_agent";

export interface DictationHintInput {
  state: DictationState;
  actions: DictationActions;
  /** The organization's longest recording, for the countdown's sentence. */
  maxSeconds: number;
  /** Set while the explanation of a crossed-out microphone is open. */
  unavailable: DictationUnavailable | null;
  /** Where an `org:settings` holder sets dictation up; null for everyone else. */
  voiceSettingsHref: string | null;
  /** Closes the explanation of a crossed-out microphone. */
  closeExplanation: () => void;
}

type Translate = ReturnType<typeof useTranslations>;

/** The curve the strip slides on: quick out from behind the box, soft landing. */
const EASE_OUT = [0.22, 1, 0.36, 1] as const;

const strong = (chunks: ReactNode) => (
  <strong className="text-foreground font-semibold">{chunks}</strong>
);

function StripButton({
  primary = false,
  disabled = false,
  onClick,
  children,
}: {
  primary?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant={primary ? "default" : "ghost"}
      disabled={disabled}
      onClick={onClick}
      className="h-7 px-2.5 text-xs pointer-coarse:h-11"
    >
      {children}
    </Button>
  );
}

/** The explanation for an engine that is on but not set up: whom to ask, or where to go. */
function notSetUp(t: Translate, href: string | null): ReactNode {
  return (
    <>
      {strong(t("hint.notSetUpTitle"))} {t("hint.notSetUpBody")}{" "}
      {href === null ? (
        t("askAdmin")
      ) : (
        <Link href={href} className="text-foreground font-medium underline underline-offset-[3px]">
          {t("openVoiceSettings")}
        </Link>
      )}
    </>
  );
}

/**
 * What the strip under the composer says, or `null` when it is shut.
 *
 * In priority order: the explanation somebody asked for, the browser's
 * permission prompt, the near-limit countdown, the silence hint, then whatever
 * ended the last attempt. Pure, so every branch is a table row in the test.
 */
export function dictationHint(input: DictationHintInput, t: Translate): StripHint | null {
  const { state, actions, maxSeconds, unavailable, voiceSettingsHref, closeExplanation } = input;
  const dismiss = <StripButton onClick={actions.dismiss}>{t("dismiss")}</StripButton>;
  const close = <StripButton onClick={closeExplanation}>{t("dismiss")}</StripButton>;
  const keep = (reason: string, sentence: ReactNode): StripHint => ({
    key: reason,
    tone: "error",
    icon: CircleAlert,
    message: (
      <>
        {strong(t("hint.failedTitle"))} {sentence}{" "}
        {t("hint.keptBody", { duration: clock(state.elapsed) })}
      </>
    ),
    actions: (
      <>
        <StripButton primary onClick={actions.retry} disabled={state.retryAfter !== null}>
          {state.retryAfter === null
            ? t("retry")
            : t("retryCountdown", { seconds: state.retryAfter })}
        </StripButton>
        <StripButton onClick={actions.dismiss}>{t("discard")}</StripButton>
      </>
    ),
  });

  if (unavailable === "no_agent") {
    return {
      key: "noAgent",
      tone: "hint",
      icon: MicOff,
      message: (
        <>
          {strong(t("hint.noAgentTitle"))} {t("hint.noAgentBody")}
        </>
      ),
      actions: close,
    };
  }
  if (unavailable === "not_ready") {
    return {
      key: "notReady",
      tone: "hint",
      icon: MicOff,
      message: notSetUp(t, voiceSettingsHref),
      actions: close,
    };
  }
  if (state.phase === "requesting") {
    return {
      key: "requesting",
      tone: "hint",
      icon: Lock,
      message: t.rich("hint.requesting", { strong }),
    };
  }
  if (state.phase === "recording" && state.remaining !== null) {
    return {
      key: "nearLimit",
      tone: "warn",
      icon: TriangleAlert,
      message: t.rich("hint.nearLimit", {
        strong,
        remaining: clock(state.remaining),
        limit: clock(maxSeconds),
      }),
    };
  }
  if (state.phase === "recording" && state.silent) {
    return {
      key: "silent",
      tone: "hint",
      icon: MicOff,
      message: t.rich("hint.silent", { strong }),
    };
  }
  if (state.phase === "too_short") {
    return {
      key: "tooShort",
      tone: "hint",
      icon: Info,
      message: t.rich("hint.tooShort", { strong }),
      actions: dismiss,
    };
  }
  if (state.phase !== "failed") return null;

  switch (state.reason) {
    case "mic_denied":
      return {
        key: "micDenied",
        tone: "error",
        icon: Lock,
        message: t.rich("hint.micDenied", { strong }),
        actions: (
          <>
            <StripButton primary onClick={() => void actions.start()}>
              {t("tryAgain")}
            </StripButton>
            {dismiss}
          </>
        ),
      };
    case "mic_insecure":
      return {
        key: "micInsecure",
        tone: "hint",
        icon: Info,
        message: t.rich("hint.micInsecure", { strong }),
        actions: dismiss,
      };
    case "mic_not_found":
    case "mic_busy":
      return {
        key: state.reason === "mic_busy" ? "micBusy" : "micNotFound",
        tone: "hint",
        icon: MicOff,
        message: t.rich(state.reason === "mic_busy" ? "hint.micBusy" : "hint.micNotFound", {
          strong,
        }),
        actions: (
          <>
            <StripButton primary onClick={() => void actions.start()}>
              {t("tryAgain")}
            </StripButton>
            {dismiss}
          </>
        ),
      };
    case "not_configured":
      return {
        key: "notConfigured",
        tone: "hint",
        icon: MicOff,
        message: notSetUp(t, voiceSettingsHref),
        actions: dismiss,
      };
    case "empty":
      return {
        key: "empty",
        tone: "hint",
        icon: Mic,
        message: t.rich("hint.empty", { strong }),
        actions: (
          <>
            <StripButton primary onClick={() => void actions.start()}>
              {t("recordAgain")}
            </StripButton>
            {dismiss}
          </>
        ),
      };
    case "too_large":
      return {
        key: "tooLarge",
        tone: "error",
        icon: CircleAlert,
        message: t.rich("hint.tooLarge", { strong }),
        actions: dismiss,
      };
    case "unsupported_type":
      return {
        key: "unsupported",
        tone: "error",
        icon: CircleAlert,
        message: t.rich("hint.unsupported", { strong }),
        actions: dismiss,
      };
    case "timeout":
      return keep("timeout", t("hint.timeoutBody"));
    case "rate_limited":
      return keep("rateLimited", t("hint.rateLimitedBody"));
    case "offline":
      return keep("offline", t("hint.offlineBody"));
    default:
      return keep("providerError", t("hint.providerErrorBody"));
  }
}

/**
 * The strip under the composer: attached to the box, sharing its border, and
 * sliding out from behind it.
 *
 * It sits below the box in the stack and is clipped by its own wrapper, so on
 * the way in it comes out from under the box's bottom edge and on the way out
 * goes back under it. Swapping one hint for another inside an open strip
 * cross-fades the text rather than sliding again. Under reduced motion it
 * appears and disappears at once.
 *
 * The text wraps and the strip grows: a hint that only fits in English is a
 * hint a German reader does not get.
 *
 * The polite live region around it is always mounted, empty while the strip is
 * shut: a region inserted already holding its text is not read out by most
 * screen readers, so the silence hint would go unheard. An error is its own
 * `alert`, inserted with each new message, and the region is switched off
 * around it so it is not read twice.
 */
export function DictationStrip({ hint }: { hint: StripHint | null }) {
  const reduced = useReducedMotion();
  const slide = reduced ? { duration: 0 } : { duration: 0.23, ease: EASE_OUT };
  const fade = reduced ? { duration: 0 } : { duration: 0.18, ease: "linear" as const };
  const error = hint?.tone === "error";

  return (
    <div data-testid="dictation-strip" aria-live={error ? "off" : "polite"}>
      <AnimatePresence initial={false}>
        {hint && (
          <motion.div
            key="strip"
            className="relative z-0 overflow-hidden"
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            transition={slide}
          >
            <motion.div
              data-testid="dictation-strip-panel"
              initial={{ y: "-100%" }}
              animate={{ y: 0 }}
              exit={{ y: "-100%" }}
              transition={slide}
              className={cn(
                "border-border text-muted-foreground relative rounded-b-2xl border border-t-0 px-3.5 py-2.5 text-[12.5px] leading-[1.45] break-words transition-colors",
                error ? "bg-destructive/10" : "bg-muted",
              )}
            >
              <AnimatePresence mode="popLayout" initial={false}>
                <motion.div
                  key={hint.key}
                  role={error ? "alert" : undefined}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={fade}
                  className="flex flex-wrap items-start gap-x-2.5 gap-y-1.5"
                >
                  <hint.icon
                    aria-hidden="true"
                    className={cn(
                      "mt-0.5 h-3.5 w-3.5 shrink-0",
                      hint.tone === "error" && "text-destructive",
                      hint.tone === "warn" && "text-warning",
                    )}
                  />
                  <p data-testid="dictation-strip-text" className="min-w-0 flex-[1_1_200px]">
                    {hint.message}
                  </p>
                  {hint.actions && (
                    <div className="ml-auto flex flex-wrap gap-1.5">{hint.actions}</div>
                  )}
                </motion.div>
              </AnimatePresence>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
