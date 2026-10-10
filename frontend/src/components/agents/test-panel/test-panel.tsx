"use client";

import { useEffect, useRef, useState } from "react";
import { Pin, PanelRightClose, Plus, Repeat, RotateCcw, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { defaultLocale } from "@/i18n";
import { AGENT_TEST_FRAME_PATH } from "@/lib/assistant-frame";
import { ASK, NEW, REPLAY, type ToFrame } from "@/lib/assistant-messages";
import {
  readTestPanel,
  TEST_PANEL_OPEN,
  writeTestPanel,
  type TestPanelState,
} from "@/lib/test-panel-state";
import type { AgentEnvironment } from "@/types/agents";

const MIN_WIDTH = 320;
const MAX_WIDTH = 820;

interface TestPanelProps {
  agentId: string;
  /** Whether the agent has a version; without one only the draft can answer. */
  published: boolean;
  environments: AgentEnvironment[];
  /** The Builder is still storing an edit, which a draft test would not see yet. */
  saving: boolean;
  onClose: () => void;
}

/**
 * Try the agent beside the Builder while building it (#2074).
 *
 * The real chat, in a frame of its own, answering as the unpublished draft or as
 * one environment's version - every turn a test run, budgeted and recorded. It
 * shares the page's width rather than covering the Builder, can be resized from
 * its edge, and keeps its width, what answers and the pinned prompts per agent.
 */
export function TestPanel({ agentId, published, environments, saving, onClose }: TestPanelProps) {
  const t = useTranslations("agents");
  const locale = useLocale();
  const prefix = locale === defaultLocale ? "" : `/${locale}`;
  const frame = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<TestPanelState>(() => readTestPanel(agentId));
  const [draftPrompt, setDraftPrompt] = useState("");
  // An environment removed since it was chosen, or a draft the agent no longer
  // offers anything beside, falls back to what can answer.
  const known = state.mode === "draft" || environments.some((env) => env.id === state.mode);
  const mode = known && (published || state.mode === "draft") ? state.mode : "draft";
  const chosen = environments.find((env) => env.id === mode);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute(TEST_PANEL_OPEN, "");
    return () => root.removeAttribute(TEST_PANEL_OPEN);
  }, []);

  const update = (next: Partial<TestPanelState>) => {
    const merged = { ...state, ...next };
    setState(merged);
    writeTestPanel(agentId, merged);
  };
  const post = (message: ToFrame) =>
    frame.current?.contentWindow?.postMessage(message, window.location.origin);

  // Dragged from its left edge: wider as the pointer moves left. Stored once, on
  // release, rather than on every pixel of the drag.
  const startResize = (event: React.PointerEvent) => {
    const startX = event.clientX;
    const start = state;
    let width = start.width;
    const move = (moved: PointerEvent) => {
      width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, start.width + startX - moved.clientX));
      setState((current) => ({ ...current, width }));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      writeTestPanel(agentId, { ...start, width });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };

  const pin = () => {
    const text = draftPrompt.trim();
    if (!text || state.pinned.includes(text)) return;
    update({ pinned: [...state.pinned, text] });
    setDraftPrompt("");
  };

  return (
    <aside
      aria-label={t("testPanel")}
      data-tour="agent-test-panel"
      style={{ "--test-panel-width": `${state.width}px` } as React.CSSProperties}
      className="bg-background fixed inset-0 z-40 flex flex-col lg:sticky lg:top-4 lg:z-auto lg:h-[calc(100vh-6rem)] lg:w-[var(--test-panel-width)] lg:shrink-0 lg:rounded-xl lg:border"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("testPanelResize")}
        onPointerDown={startResize}
        className="hover:bg-border absolute inset-y-0 -left-1.5 hidden w-3 cursor-col-resize rounded lg:block"
      />
      <header className="space-y-2 border-b p-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">{t("testPanel")}</h2>
          <Select value={mode} onValueChange={(value) => update({ mode: value })}>
            <SelectTrigger className="h-8 flex-1" aria-label={t("testPanelWhatAnswers")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="draft">{t("testPanelDraft")}</SelectItem>
              {published &&
                environments.map((env) => (
                  <SelectItem key={env.id} value={env.id}>
                    {t("testPanelEnvironment", { name: env.name, version: env.version })}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("testPanelNew")}
            title={t("testPanelNew")}
            onClick={() => post({ type: NEW })}
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("testPanelReplay")}
            title={t("testPanelReplay")}
            onClick={() => post({ type: REPLAY })}
          >
            <Repeat className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label={t("testPanelClose")} onClick={onClose}>
            <PanelRightClose className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-muted-foreground text-xs" role="status">
          {mode === "draft"
            ? saving
              ? t("testPanelDraftSaving")
              : t("testPanelDraftHint")
            : t("testPanelEnvironmentHint", {
                name: chosen?.name ?? "",
                version: chosen?.version ?? 0,
              })}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          {state.pinned.map((text) => (
            <span
              key={text}
              className="bg-muted flex max-w-full items-center gap-1 rounded-full py-0.5 pr-1 pl-2.5 text-xs"
            >
              <button
                type="button"
                className="truncate hover:underline"
                title={text}
                onClick={() => post({ type: ASK, text })}
              >
                {text}
              </button>
              <button
                type="button"
                aria-label={t("testPanelUnpin", { text })}
                onClick={() => update({ pinned: state.pinned.filter((entry) => entry !== text) })}
                className="text-muted-foreground hover:text-foreground rounded-full p-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <form
            className="flex min-w-40 flex-1 items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              pin();
            }}
          >
            <Pin className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
            <Input
              value={draftPrompt}
              onChange={(event) => setDraftPrompt(event.target.value)}
              placeholder={t("testPanelPinPlaceholder")}
              aria-label={t("testPanelPin")}
              className="h-7 text-xs"
              maxLength={500}
            />
            <Button
              type="submit"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={t("testPanelPin")}
              disabled={!draftPrompt.trim()}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </form>
        </div>
      </header>
      <iframe
        key={mode}
        ref={frame}
        title={t("testPanel")}
        src={`${prefix}${AGENT_TEST_FRAME_PATH}?agent=${agentId}&mode=${mode}`}
        className="min-h-0 w-full flex-1 border-0 lg:rounded-b-xl"
      />
    </aside>
  );
}
