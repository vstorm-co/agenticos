"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import { cn } from "@/lib/utils";
import type { AssistantState } from "@/types/assistant";

import { AssistantFace, AssistantLauncher, WINDOW_CLASSES, WidgetRoot } from "./assistant-launcher";

/** How long the assistant "types" each message of the walkthrough. */
export const TYPING_MS = 900;

/** The walkthrough, as keys under `assistantWidget.setup.steps`. */
const STEPS = ["intro", "key", "settings", "model", "done"] as const;

/**
 * The AI Architect before it has a model (#2063).
 *
 * It cannot answer anything yet, so it does the one thing it can without a
 * model: a scripted conversation, typed out a message at a time, walking
 * through connecting one - get a key, open Settings → Assistant, paste it,
 * choose a model. Everybody who may talk to it sees the walkthrough, so
 * everybody knows what is missing; only an administrator is given the button,
 * and anybody else is told who can do it.
 */
export function AssistantSetup({
  assistant,
  agentId,
}: {
  assistant: AssistantState;
  agentId: string;
}) {
  const t = useTranslations("assistantWidget");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [everOpened, setEverOpened] = useState(false);
  const steps = assistant.can_configure ? STEPS : [...STEPS.slice(0, -1), "askAdmin" as const];

  return (
    <WidgetRoot>
      {everOpened && (
        <div
          role="dialog"
          data-assistant-window
          aria-label={t("setup.title")}
          className={cn(WINDOW_CLASSES, !open && "hidden")}
        >
          <header className="border-border flex items-center gap-2 border-b px-3 py-2">
            <AssistantFace assistant={assistant} agentId={agentId} size="sm" />
            <p className="min-w-0 flex-1 truncate text-sm font-semibold">{assistant.name}</p>
            <button
              type="button"
              aria-label={t("close")}
              title={t("close")}
              onClick={() => setOpen(false)}
              className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] rounded-md p-1.5"
            >
              <X className="h-4 w-4" />
            </button>
          </header>
          <Walkthrough
            name={assistant.name}
            steps={steps}
            action={
              assistant.can_configure ? (
                <Button size="sm" onClick={() => router.push(ROUTES.SETTINGS_ASSISTANT)}>
                  {t("setup.openSettings")}
                </Button>
              ) : null
            }
          />
        </div>
      )}

      {!everOpened && (
        <button
          type="button"
          onClick={() => {
            setOpen(true);
            setEverOpened(true);
          }}
          className="bg-background border-border fixed right-4 bottom-36 z-50 max-w-[17rem] rounded-2xl rounded-br-sm border px-4 py-3 text-left text-sm leading-snug shadow-lg md:right-6 md:bottom-24"
        >
          {t("setup.bubble")}
        </button>
      )}

      <AssistantLauncher
        assistant={assistant}
        agentId={agentId}
        open={open}
        onToggle={() => {
          setOpen(!open);
          setEverOpened(true);
        }}
      />
    </WidgetRoot>
  );
}

function Walkthrough({
  name,
  steps,
  action,
}: {
  name: string;
  steps: readonly string[];
  action: React.ReactNode;
}) {
  const t = useTranslations("assistantWidget");
  const [shown, setShown] = useState(1);
  const typing = shown < steps.length;
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Follow the conversation as it is typed, the way a chat does.
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    if (!typing) return;
    const timer = setTimeout(() => setShown((count) => count + 1), TYPING_MS);
    return () => clearTimeout(timer);
  }, [shown, typing]);

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
      {steps.slice(0, shown).map((step) => (
        <p
          key={step}
          className="bg-muted max-w-[90%] rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm leading-relaxed"
        >
          {t.rich(`setup.steps.${step}`, { name, b: (chunks) => <strong>{chunks}</strong> })}
        </p>
      ))}
      {typing ? (
        <p className="text-muted-foreground text-xs">{t("setup.typing", { name })}</p>
      ) : (
        action
      )}
      <div ref={end} />
    </div>
  );
}
