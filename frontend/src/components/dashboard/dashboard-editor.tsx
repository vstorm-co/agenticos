"use client";

import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { BookmarkPlus, ChevronDown, Plus, RotateCcw, SeparatorHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import {
  ARRANGED_GRID_CLASS,
  ROW_CLASS,
  SPAN_CLASS,
  type LayoutItem,
} from "@/lib/dashboard/layouts";
import { Period } from "@/lib/dashboard/period";
import { newDivider, newPlacement, toStored, type StoredEntry } from "@/lib/dashboard/preference";
import {
  accentDecoration,
  isAccentColour,
  type Rows,
  type SectionAccent,
  type Span,
  type WidgetDef,
  type WidgetId,
} from "@/lib/dashboard/registry";
import { cn } from "@/lib/utils";
import { AddWidgetDialog } from "./add-widget-dialog";
import { SaveActiveDialog } from "./save-active-dialog";
import {
  addWidgetToSection,
  fromEditorSections,
  moveSection,
  moveWidget,
  moveWidgetBy,
  patchDivider,
  removeSection,
  removeWidget,
  resizeWidget,
  swapWidgets,
  toEditorSections,
  type EditorSection,
  type EditorWidget,
} from "./editor-model";
import { SavePresetDialog } from "./save-preset-dialog";
import { SectionDividerCard } from "./section-divider-card";
import { useFlip } from "./use-flip";
import { WidgetEditCard } from "./widget-edit-card";

interface DashboardEditorProps {
  /** The layout to start arranging from - already gated and flattened. */
  initialEntries: LayoutItem[];
  /** The widgets the caller may add, gated. */
  catalog: WidgetDef[];
  /** The period filter, so the live cards show the same data as the page. */
  period: Period;
  /** Persist the arrangement as the active layout; `false` if the save failed. */
  onSave: (entries: StoredEntry[]) => Promise<boolean>;
  onCancel: () => void;
  /** Discard the saved arrangement, back to the audience default. */
  onReset: () => Promise<void>;
  /** Keep the current draft under a name, without leaving edit mode. */
  onSaveAsPreset: (name: string, entries: StoredEntry[]) => Promise<void>;
  /**
   * Whether the editor opened on a blank grid ("New blank layout"). A plain
   * save of a from-scratch layout writes only the replaceable active slot, so
   * this gates the save behind a warning that offers the permanent template.
   */
  startedBlank: boolean;
}

/** How far the pointer must travel before a press becomes a drag rather than a click. */
const DRAG_THRESHOLD = 4;

type Drag = { kind: "widget" | "section"; uid: string };

/**
 * Which section the pointer is over, where within it a dropped card lands, and
 * which card sits under the pointer (ringed as the drop target). The section is
 * chosen by the pointer's Y against each section block, nearest if it sits in a
 * gap; the local index counts the section's *other* cards that fall before the
 * pointer in reading order — the dragged one excluded — so the card settles into
 * the slot the pointer names. An 8px horizontal dead-band keeps a cursor near a
 * card's centre from flickering between two slots.
 */
function hitTestWidget(
  container: HTMLElement,
  x: number,
  y: number,
  draggedUid: string,
): { sectionUid: string; index: number; overUid: string | null } | null {
  // Only droppable sections: a collapsed one renders its `[data-sec-uid]` block
  // but no grid, so dropping over it (or a gap beside it) would land the card in
  // a folded section where it reads as vanished. Skipping them sends the card to
  // the nearest open section instead.
  const blocks = Array.from(container.querySelectorAll<HTMLElement>("[data-sec-uid]")).filter(
    (block) => block.querySelector("[data-sec-grid]"),
  );
  let best: HTMLElement | null = null;
  let bestDistance = Infinity;
  for (const block of blocks) {
    const rect = block.getBoundingClientRect();
    if (y >= rect.top && y <= rect.bottom) {
      best = block;
      break;
    }
    const distance = y < rect.top ? rect.top - y : y - rect.bottom;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = block;
    }
  }
  if (!best?.dataset.secUid) return null;
  const grid = best.querySelector<HTMLElement>("[data-sec-grid]");
  let index = 0;
  let overUid: string | null = null;
  if (grid) {
    const cells = Array.from(grid.querySelectorAll<HTMLElement>("[data-widget-uid]")).filter(
      (cell) => cell.dataset.widgetUid !== draggedUid,
    );
    for (const cell of cells) {
      const rect = cell.getBoundingClientRect();
      if (rect.bottom <= y) index += 1;
      else if (rect.top <= y && rect.left + rect.width / 2 + 8 < x) index += 1;
      if (y >= rect.top && y <= rect.bottom && x >= rect.left && x <= rect.right) {
        overUid = cell.dataset.widgetUid ?? null;
      }
    }
  }
  return { sectionUid: best.dataset.secUid, index, overUid };
}

/** The section index the pointer's Y names, counting the other section blocks above it. */
function hitTestSection(container: HTMLElement, y: number, draggedUid: string): number {
  let index = 0;
  for (const block of container.querySelectorAll<HTMLElement>("[data-sec-uid]")) {
    if (block.dataset.secUid === draggedUid) continue;
    const rect = block.getBoundingClientRect();
    if (rect.top + rect.height / 2 < y) index += 1;
  }
  return index;
}

/**
 * Edit mode: a working draft arranged by dragging, resizing in two dimensions,
 * hiding and adding cards, saved or discarded as a whole. The draft is local
 * until saved, so experimenting costs nothing and Cancel is a true undo. Reset
 * discards the saved arrangement entirely; Save as preset keeps the current
 * draft on the shelf under a name without leaving.
 *
 * The arrangement is a list of sections, each an independent grid under its own
 * heading. A card is dragged to reorder — within its section or into another;
 * nothing shuffles under the cursor, the drop target is just ringed, and on drop
 * every moved card glides to its new place at once (`useFlip`). Cards drag-resize
 * from eight grips. A section heading carries a colour that tints its cards, a
 * collapse toggle, and its own drag grip to reorder the whole band. Adding a
 * card is not a fiddly drop-on-the-grid: it lands at the bottom (or in a section
 * chosen from the split button) and pops into view, ready to drag from there.
 */
export function DashboardEditor({
  initialEntries,
  catalog,
  period,
  onSave,
  onCancel,
  onReset,
  onSaveAsPreset,
  startedBlank,
}: DashboardEditorProps) {
  const t = useTranslations("dashboard");
  // Two uid spaces that never collide: the seed items minted once here with a
  // local counter (no ref read during render), and everything added later with
  // `mint`, touched only in handlers.
  const [sections, setSections] = useState<EditorSection[]>(() => {
    let seed = 0;
    return toEditorSections(initialEntries, () => `seed-${seed++}`);
  });
  const nextUid = useRef(0);
  const mint = useCallback(() => `u${nextUid.current++}`, []);
  // Teardown for an in-flight drag, so an unmount mid-drag does not leave the
  // window listeners (and `document.body.style.userSelect`) behind.
  const dragTeardown = useRef<(() => void) | null>(null);
  useEffect(() => () => dragTeardown.current?.(), []);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [presetOpen, setPresetOpen] = useState(false);
  // The blank-start save warning, and whether naming a template from it should
  // also apply the layout and leave the editor (so "save as template" there is
  // one terminal act, not a preset the person must then apply by hand).
  const [confirmSaveOpen, setConfirmSaveOpen] = useState(false);
  const [presetThenApply, setPresetThenApply] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  // The card the pointer is over while dragging — ringed as the drop target.
  // Nothing reorders until the drop, so the ring is the only live feedback.
  const [overUid, setOverUid] = useState<string | null>(null);
  // The section a picked card lands in; and the card just added, for the pop.
  const [addTarget, setAddTarget] = useState<string | null>(null);
  const [poppedUid, setPoppedUid] = useState<string | null>(null);

  const runBusy = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };

  const resize = (uid: string, span: Span, rows: Rows) =>
    setSections((current) => resizeWidget(current, uid, span, rows));
  const setLabel = (uid: string, label: string) =>
    setSections((current) => patchDivider(current, uid, { label }));
  const setAccent = (uid: string, accent: SectionAccent) =>
    setSections((current) => patchDivider(current, uid, { accent }));
  const toggleCollapse = (uid: string) =>
    setSections((current) =>
      current.map((section) =>
        section.uid === uid && section.divider
          ? { ...section, divider: { ...section.divider, collapsed: !section.divider.collapsed } }
          : section,
      ),
    );
  const addSection = () =>
    setSections((current) => [...current, { uid: mint(), divider: newDivider(), widgets: [] }]);

  // Add a card: it lands in the chosen section (or the last one, the bottom of
  // the layout) and pops into view — no on-grid drop to aim. The split button's
  // caret picks the section; "New section" makes one and targets it.
  const openAdd = (target: string | null) => {
    setAddTarget(target);
    setDialogOpen(true);
  };
  const addToNewSection = () => {
    const uid = mint();
    setSections((current) => [...current, { uid, divider: newDivider(), widgets: [] }]);
    openAdd(uid);
  };
  const handlePick = (widget: WidgetId) => {
    const card: EditorWidget = { ...newPlacement(widget), uid: mint() };
    const target =
      addTarget && sections.some((section) => section.uid === addTarget)
        ? addTarget
        : (sections.at(-1)?.uid ?? null);
    if (target === null) {
      setSections([{ uid: mint(), divider: null, widgets: [card] }]);
    } else {
      setSections((current) =>
        patchDivider(addWidgetToSection(current, target, card), target, { collapsed: false }),
      );
    }
    setDialogOpen(false);
    setAddTarget(null);
    setPoppedUid(card.uid);
  };

  // FLIP re-runs whenever the rendered order, any card's size, or a section's
  // collapse changes — the things that move or hide cards. A divider's label or
  // colour is left out: it moves nothing.
  const signature = sections
    .map(
      (section) =>
        `${section.uid}:${section.divider ? (section.divider.collapsed ? "c" : "o") : "-"}:` +
        section.widgets.map((widget) => `${widget.uid}.${widget.span}.${widget.rows}`).join(","),
    )
    .join("|");
  const gridRef = useFlip<HTMLDivElement>(signature);

  // The whole grid owns the drag, delegated from one pointerdown: a press on a
  // resize grip or a control (`data-resize`/`data-no-drag`) is not a drag; a
  // press on a section grip drags the band, and anywhere else on a card drags
  // the card. It arms on pointerdown and activates only past a small threshold,
  // so a plain click never nudges the order. Nothing reorders while the pointer
  // moves — the target is only tracked (and ringed) — and the move is applied
  // once on drop, so the cards glide to their new places then rather than
  // shuffling live under the cursor. Releasing over another card swaps the two;
  // releasing in a gap or an empty section inserts, which is what carries a card
  // across a divider.
  const onGridPointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("[data-resize]") || target.closest("[data-no-drag]")) return;
    const grip = target.closest<HTMLElement>("[data-section-grip]");
    const block = target.closest<HTMLElement>("[data-sec-uid]");
    const cell = target.closest<HTMLElement>("[data-widget-uid]");
    const armed: Drag | null = grip
      ? block?.dataset.secUid
        ? { kind: "section", uid: block.dataset.secUid }
        : null
      : cell?.dataset.widgetUid
        ? { kind: "widget", uid: cell.dataset.widgetUid }
        : null;
    if (!armed) return;

    const startX = event.clientX;
    const startY = event.clientY;
    let active = false;
    let widgetDrop: { sectionUid: string; index: number } | null = null;
    // The card the pointer is over, if any. A drop straight onto another card
    // swaps the two; a drop in a gap or an empty section falls back to inserting
    // at `widgetDrop`, which is what still carries a card into another section.
    let overDrop: string | null = null;
    let sectionDrop: number | null = null;
    const move = (moveEvent: PointerEvent) => {
      if (!active) {
        if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < DRAG_THRESHOLD) {
          return;
        }
        active = true;
        setDrag(armed);
        document.body.style.userSelect = "none";
      }
      const container = gridRef.current;
      if (!container) return;
      if (armed.kind === "widget") {
        const hit = hitTestWidget(container, moveEvent.clientX, moveEvent.clientY, armed.uid);
        if (!hit) return;
        widgetDrop = { sectionUid: hit.sectionUid, index: hit.index };
        overDrop = hit.overUid;
        setOverUid((current) => (current === hit.overUid ? current : hit.overUid));
      } else {
        sectionDrop = hitTestSection(container, moveEvent.clientY, armed.uid);
      }
    };
    const finish = (endEvent: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      dragTeardown.current = null;
      document.body.style.userSelect = "";
      // A cancelled gesture (a touch scroll taking over the grip, which has no
      // `touch-action: none`) tears down without applying the drop, so a leaked
      // pointerup can no longer fire the stale move on the next click.
      const apply = endEvent.type !== "pointercancel" && active;
      if (apply && armed.kind === "widget" && overDrop) {
        const target = overDrop;
        setSections((current) => swapWidgets(current, armed.uid, target));
      } else if (apply && armed.kind === "widget" && widgetDrop) {
        const drop = widgetDrop;
        setSections((current) => moveWidget(current, armed.uid, drop.sectionUid, drop.index));
      } else if (apply && armed.kind === "section" && sectionDrop !== null) {
        const index = sectionDrop;
        setSections((current) => moveSection(current, armed.uid, index));
      }
      setDrag(null);
      setOverUid(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    dragTeardown.current = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      document.body.style.userSelect = "";
    };
  };

  // A just-added card scrolls into view and pops; the flag clears once the
  // one-shot animation has run.
  useEffect(() => {
    if (!poppedUid) return;
    const card = gridRef.current?.querySelector<HTMLElement>(`[data-widget-uid="${poppedUid}"]`);
    card?.scrollIntoView({ behavior: "smooth", block: "center" });
    const timer = window.setTimeout(() => setPoppedUid(null), 320);
    return () => window.clearTimeout(timer);
  }, [poppedUid, gridRef]);

  const sectionName = (section: EditorSection) =>
    section.divider
      ? section.divider.label.trim() || t("edit.untitledSection")
      : t("edit.topSection");
  const bottomTarget = sections.at(-1)?.uid ?? null;

  return (
    <div className="space-y-4">
      <div className="border-border bg-muted/30 flex flex-wrap items-center gap-2 rounded-lg border p-3">
        <p className="text-muted-foreground text-sm">{t("edit.banner")}</p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex items-center">
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 rounded-r-none"
              disabled={busy}
              onClick={() => openAdd(bottomTarget)}
            >
              <Plus className="size-3.5" aria-hidden />
              {t("edit.addWidget")}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-l-none border-l-0 px-2"
                  disabled={busy}
                  aria-label={t("edit.addToSection")}
                >
                  <ChevronDown className="size-3.5" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {sections.map((section) => (
                  <DropdownMenuItem key={section.uid} onSelect={() => openAdd(section.uid)}>
                    {sectionName(section)}
                  </DropdownMenuItem>
                ))}
                {sections.length > 0 ? <DropdownMenuSeparator /> : null}
                <DropdownMenuItem onSelect={addToNewSection}>
                  <SeparatorHorizontal className="size-3.5" aria-hidden />
                  {t("edit.newSection")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={busy}
            onClick={addSection}
          >
            <SeparatorHorizontal className="size-3.5" aria-hidden />
            {t("edit.addSection")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={busy || sections.length === 0}
            onClick={() => {
              setPresetThenApply(false);
              setPresetOpen(true);
            }}
          >
            <BookmarkPlus className="size-3.5" aria-hidden />
            {t("edit.saveAsPreset")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={busy}
            onClick={() => runBusy(onReset)}
          >
            <RotateCcw className="size-3.5" aria-hidden />
            {t("edit.reset")}
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={onCancel}>
            {t("edit.cancel")}
          </Button>
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              startedBlank
                ? setConfirmSaveOpen(true)
                : runBusy(() => onSave(toStored(fromEditorSections(sections))))
            }
          >
            {t("edit.save")}
          </Button>
        </div>
      </div>

      {sections.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
          {t("edit.emptyDraft")}
        </p>
      ) : (
        // overflow-anchor:none: a live resize changes a card's height on every
        // pointer move, and the scrolling <main> would otherwise keep re-anchoring
        // to compensate, nudging the scroll under the cursor. FLIP measures
        // relative to this container, so its glide is unaffected either way.
        <div
          ref={gridRef}
          className="space-y-6 [overflow-anchor:none]"
          onPointerDown={onGridPointerDown}
        >
          {sections.map((section) => {
            // The chosen accent previews here as it renders on the page — a
            // tinted band with a coloured rail, and a ring on each card — so a
            // colour is judged in place rather than only after saving.
            const coloured = isAccentColour(section.divider?.accent);
            const decoration = coloured ? accentDecoration(section.divider!.accent) : null;
            return (
              <div
                key={section.uid}
                data-sec-uid={section.uid}
                className={cn(
                  "space-y-2",
                  coloured && "dash-section-accent p-3",
                  decoration?.className,
                )}
                style={decoration?.style as CSSProperties | undefined}
              >
                {section.divider ? (
                  <div data-flip-id={section.uid}>
                    <SectionDividerCard
                      entry={section.divider}
                      dragging={drag?.kind === "section" && drag.uid === section.uid}
                      onLabelChange={(label) => setLabel(section.uid, label)}
                      onAccentChange={(accent) => setAccent(section.uid, accent)}
                      onToggleCollapse={() => toggleCollapse(section.uid)}
                      onRemove={() => setSections((current) => removeSection(current, section.uid))}
                    />
                  </div>
                ) : null}
                {section.divider?.collapsed ? null : (
                  <div data-sec-grid className={ARRANGED_GRID_CLASS}>
                    {section.widgets.map((widget) => (
                      <div
                        key={widget.uid}
                        data-flip-id={widget.uid}
                        data-widget-uid={widget.uid}
                        className={cn(
                          SPAN_CLASS[widget.span],
                          ROW_CLASS[widget.rows ?? "r3"],
                          coloured && "dash-tile-accent",
                          poppedUid === widget.uid && "dash-pop",
                        )}
                      >
                        <WidgetEditCard
                          entry={widget}
                          period={period}
                          dragging={drag?.kind === "widget" && drag.uid === widget.uid}
                          dropTarget={
                            drag?.kind === "widget" &&
                            drag.uid !== widget.uid &&
                            overUid === widget.uid
                          }
                          onResize={(span, rows) => resize(widget.uid, span, rows)}
                          onMove={(direction) =>
                            setSections((current) => moveWidgetBy(current, widget.uid, direction))
                          }
                          onRemove={() =>
                            setSections((current) => removeWidget(current, widget.uid))
                          }
                        />
                      </div>
                    ))}
                    {section.widgets.length === 0 ? (
                      <p className="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-xs lg:col-span-12">
                        {t("edit.emptySection")}
                      </p>
                    ) : null}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <AddWidgetDialog
        catalog={catalog}
        period={period}
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setAddTarget(null);
        }}
        onAdd={handlePick}
      />
      <SavePresetDialog
        open={presetOpen}
        onOpenChange={setPresetOpen}
        onSave={async (name) => {
          const entries = toStored(fromEditorSections(sections));
          await onSaveAsPreset(name, entries);
          // From the blank-start warning, naming the template also applies it as
          // the active layout and leaves the editor - one act, not a preset to
          // apply by hand. A failed apply has toasted its own error, so surface
          // that as the dialog's outcome rather than a clean save.
          if (presetThenApply) return onSave(entries);
          return true;
        }}
      />
      <SaveActiveDialog
        open={confirmSaveOpen}
        onOpenChange={setConfirmSaveOpen}
        busy={busy}
        onSaveActive={() => {
          setConfirmSaveOpen(false);
          runBusy(() => onSave(toStored(fromEditorSections(sections))));
        }}
        onSaveAsTemplate={() => {
          setConfirmSaveOpen(false);
          setPresetThenApply(true);
          setPresetOpen(true);
        }}
      />
    </div>
  );
}
