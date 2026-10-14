"use client";

import { useEffect, useState } from "react";
import { Columns2, GitCompare, PanelRightClose, Repeat, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  readTestPanel,
  TEST_PANEL_OPEN,
  writeTestPanel,
  type TestPanelState,
} from "@/lib/test-panel-state";
import type { ChatPrompt } from "@/components/chat/chat-container";
import { cn } from "@/lib/utils";
import { ChatScope } from "@/stores";
import type { AgentEnvironment, AgentSpec } from "@/types/agents";
import { DraftChanges } from "./draft-changes";
import { TestChat, testingFromMode } from "./test-chat";
import { TestPanelPrompts } from "./test-panel-prompts";

const MIN_WIDTH = 320;
const MAX_WIDTH = 820;
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
 * The real chat, with stores of its own, answering as the unpublished draft or as
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
  // Bumped to start both conversations afresh, by keying their scopes on it.
  const [conversation, setConversation] = useState(0);
  const [replay, setReplay] = useState(0);
  const [ask, setAsk] = useState<ChatPrompt | null>(null);
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
  const width = compare === null ? state.width : state.compareWidth;
  const sized = (from: TestPanelState, next: number): TestPanelState =>
    compare === null ? { ...from, width: next } : { ...from, compareWidth: next };

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute(TEST_PANEL_OPEN, "");
    return () => root.removeAttribute(TEST_PANEL_OPEN);
  }, []);

  // A question pinned or taken off from either conversation (#2075). The panel
  // keeps the list - idempotently, as a strict-mode updater may run twice.
  const togglePin = (text: string) =>
    setState((current) => {
      const pinned = current.pinned.includes(text)
        ? current.pinned.filter((entry) => entry !== text)
        : [...current.pinned, text];
      const next = { ...current, pinned };
      writeTestPanel(agentId, next);
      return next;
    });

  const update = (next: Partial<TestPanelState>) => {
    const merged = { ...state, ...next };
    setState(merged);
    writeTestPanel(agentId, merged);
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
    let dragged = width;
    const move = (moved: PointerEvent) => {
      dragged = Math.min(max, Math.max(MIN_WIDTH, width + startX - moved.clientX));
      setState((current) => sized(current, dragged));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      writeTestPanel(agentId, sized(start, dragged));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };

  const toggleCompare = () =>
    update({
      compare: compare === null ? (choices.find((value) => value !== mode) ?? null) : null,
    });

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
      style={{ "--test-panel-width": `${width}px` } as React.CSSProperties}
      // One gutter from the window's top and bottom, scrolled or not. The page
      // scrolls inside a container padded 2rem at the top, which a sticky offset
      // counts from - so the panel is lifted by that padding in the flow and
      // stuck 1rem above it, and both land 1rem from the window's edge. It sat
      // 48px down once scrolled and stopped 48px short of the bottom.
      className="bg-background fixed inset-0 z-40 flex flex-col lg:sticky lg:top-[-1rem] lg:z-auto lg:-mt-8 lg:h-[calc(100dvh-2rem)] lg:w-[var(--test-panel-width)] lg:shrink-0 lg:rounded-xl lg:border"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("testPanelResize")}
        onPointerDown={startResize}
        className="hover:bg-border absolute inset-y-0 -left-1.5 hidden w-3 cursor-col-resize rounded lg:block"
      />
      <header className="flex flex-col gap-2 border-b px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <h2 className="mr-1 text-sm font-semibold">{t("testPanel")}</h2>
          {picker(mode, (value) => update({ mode: value }), t("testPanelWhatAnswers"))}
          {compare !== null &&
            picker(compare, (value) => update({ compare: value }), t("testPanelComparedWith"))}
          {choices.length > 1 && (
            <Button
              variant={compare === null ? "ghost" : "secondary"}
              size="icon"
              className="h-8 w-8"
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
              className="h-8 w-8"
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
            className="h-8 w-8"
            aria-label={t("testPanelNew")}
            title={t("testPanelNew")}
            onClick={() => setConversation((count) => count + 1)}
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={t("testPanelReplay")}
            title={t("testPanelReplay")}
            onClick={() => setReplay((count) => count + 1)}
          >
            <Repeat className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={t("testPanelClose")}
            onClick={onClose}
          >
            <PanelRightClose className="h-4 w-4" />
          </Button>
        </div>
        {/* What answers is said in the conversation's own opening, as `/chat`
            says it (#2075); this line is left for what changes while you look. */}
        <p className="text-muted-foreground min-h-0 text-xs empty:hidden" role="status">
          {compare !== null
            ? t("testPanelCompareHint")
            : mode === "draft" && saving
              ? t("testPanelDraftSaving")
              : null}
        </p>
        {/* Two conversations asked the same thing need one box to ask it from. */}
        {compare !== null && (
          <TestPanelPrompts
            pinned={state.pinned}
            comparing
            onAsk={(text) => setAsk((last) => ({ id: (last?.id ?? 0) + 1, text }))}
            onPinnedChange={(pinned) => update({ pinned })}
          />
        )}
      </header>
      <div className={cn("flex min-h-0 flex-1 flex-col lg:flex-row", compare && "lg:divide-x")}>
        {modes.map((value) => (
          <div key={value} className="flex min-h-0 min-w-0 flex-1 flex-col">
            {compare !== null && (
              <p className="text-muted-foreground border-b px-3 py-1.5 text-xs font-medium">
                {label(value)}
              </p>
            )}
            <ChatScope key={`${value}:${conversation}`} agentId={agentId}>
              <TestChat
                agentId={agentId}
                testing={testingFromMode(value)}
                pinned={state.pinned}
                onTogglePin={togglePin}
                ask={ask}
                replay={replay}
              />
            </ChatScope>
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
