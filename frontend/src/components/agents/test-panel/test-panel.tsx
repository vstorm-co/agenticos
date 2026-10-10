"use client";

import { useEffect, useRef, useState } from "react";
import { Columns2, GitCompare, PanelRightClose, Repeat, RotateCcw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  Button,
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
import { cn } from "@/lib/utils";
import type { AgentEnvironment, AgentSpec } from "@/types/agents";
import { DraftChanges } from "./draft-changes";
import { TestPanelPrompts } from "./test-panel-prompts";

const MIN_WIDTH = 320;
const MAX_WIDTH = 820;
/** Two chats side by side need room; comparing widens the panel to at least this. */
const COMPARE_WIDTH = 880;
const COMPARE_MAX_WIDTH = 1400;

interface TestPanelProps {
  agentId: string;
  /** The version the agent serves by default; null until something is published. */
  currentVersionId: string | null;
  environments: AgentEnvironment[];
  /** The draft as the Builder holds it, for the changes it makes against the version. */
  draftSpec: AgentSpec;
  /** The Builder is still storing an edit, which a draft test would not see yet. */
  saving: boolean;
  onClose: () => void;
}

/**
 * Try the agent beside the Builder while building it (#2074).
 *
 * The real chat, in a frame of its own, answering as the unpublished draft or as
 * one environment's version - every turn a test run, budgeted and recorded. Two
 * of them can answer side by side, asked the same thing at once. It shares the
 * page's width rather than covering the Builder, can be resized from its edge,
 * and keeps its width, what answers and the pinned prompts per agent.
 */
export function TestPanel({
  agentId,
  currentVersionId,
  environments,
  draftSpec,
  saving,
  onClose,
}: TestPanelProps) {
  const t = useTranslations("agents");
  const locale = useLocale();
  const prefix = locale === defaultLocale ? "" : `/${locale}`;
  const first = useRef<HTMLIFrameElement>(null);
  const second = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<TestPanelState>(() => readTestPanel(agentId));
  const [showingChanges, setShowingChanges] = useState(false);
  const published = currentVersionId !== null;
  // An environment removed since it was chosen, or anything but the draft on an
  // agent with nothing published, falls back to what can answer.
  const answers = (value: string) =>
    value === "draft" || (published && environments.some((env) => env.id === value));
  const mode = answers(state.mode) ? state.mode : "draft";
  const compare =
    state.compare !== null && state.compare !== mode && answers(state.compare)
      ? state.compare
      : null;
  const modes = compare === null ? [mode] : [mode, compare];

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
  const post = (message: ToFrame) => {
    for (const frame of [first, second]) {
      frame.current?.contentWindow?.postMessage(message, window.location.origin);
    }
  };
  const label = (value: string) => {
    const env = environments.find((entry) => entry.id === value);
    return env
      ? t("testPanelEnvironment", { name: env.name, version: env.version })
      : t("testPanelDraft");
  };
  const choices = ["draft", ...(published ? environments.map((env) => env.id) : [])];

  // Dragged from its left edge: wider as the pointer moves left. Stored once, on
  // release, rather than on every pixel of the drag.
  const startResize = (event: React.PointerEvent) => {
    const startX = event.clientX;
    const start = state;
    const max = compare === null ? MAX_WIDTH : COMPARE_MAX_WIDTH;
    let width = start.width;
    const move = (moved: PointerEvent) => {
      width = Math.min(max, Math.max(MIN_WIDTH, start.width + startX - moved.clientX));
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

  const toggleCompare = () =>
    compare === null
      ? update({
          compare: choices.find((value) => value !== mode) ?? null,
          width: Math.max(state.width, COMPARE_WIDTH),
        })
      : update({ compare: null, width: Math.min(state.width, MAX_WIDTH) });

  const picker = (value: string, onChange: (next: string) => void, name: string) => (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 min-w-0 flex-1" aria-label={name}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {choices.map((choice) => (
          <SelectItem key={choice} value={choice}>
            {label(choice)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

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
          {picker(mode, (value) => update({ mode: value }), t("testPanelWhatAnswers"))}
          {compare !== null &&
            picker(compare, (value) => update({ compare: value }), t("testPanelComparedWith"))}
          {choices.length > 1 && (
            <Button
              variant={compare === null ? "ghost" : "secondary"}
              size="icon"
              aria-label={t("testPanelCompare")}
              aria-pressed={compare !== null}
              title={t("testPanelCompare")}
              onClick={toggleCompare}
            >
              <Columns2 className="h-4 w-4" />
            </Button>
          )}
          {published && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("testPanelChanges")}
              title={t("testPanelChanges")}
              onClick={() => setShowingChanges(true)}
            >
              <GitCompare className="h-4 w-4" />
            </Button>
          )}
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
          {compare !== null
            ? t("testPanelCompareHint")
            : mode !== "draft"
              ? t("testPanelEnvironmentHint", {
                  name: environments.find((env) => env.id === mode)?.name ?? "",
                  version: environments.find((env) => env.id === mode)?.version ?? 0,
                })
              : saving
                ? t("testPanelDraftSaving")
                : t("testPanelDraftHint")}
        </p>
        <TestPanelPrompts
          pinned={state.pinned}
          comparing={compare !== null}
          onAsk={(text) => post({ type: ASK, text })}
          onPinnedChange={(pinned) => update({ pinned })}
        />
      </header>
      <div className={cn("flex min-h-0 flex-1 flex-col lg:flex-row", compare && "lg:divide-x")}>
        {modes.map((value, index) => (
          <div key={value} className="flex min-h-0 min-w-0 flex-1 flex-col">
            {compare !== null && (
              <p className="text-muted-foreground border-b px-3 py-1.5 text-xs font-medium">
                {label(value)}
              </p>
            )}
            <iframe
              ref={index === 0 ? first : second}
              title={index === 0 ? t("testPanel") : t("testPanelComparedWith")}
              src={`${prefix}${AGENT_TEST_FRAME_PATH}?agent=${agentId}&mode=${value}`}
              className="min-h-0 w-full flex-1 border-0 lg:rounded-b-xl"
            />
          </div>
        ))}
      </div>
      {showingChanges && currentVersionId !== null && (
        <DraftChanges
          agentId={agentId}
          versionId={currentVersionId}
          draftSpec={draftSpec}
          onClose={() => setShowingChanges(false)}
        />
      )}
    </aside>
  );
}
