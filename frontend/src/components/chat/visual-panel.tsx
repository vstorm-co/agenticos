"use client";

import {
  AppWindow,
  Code2,
  Copy,
  Download,
  Maximize2,
  RotateCw,
  Shapes,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { toast } from "sonner";

import { Dialog, DialogContent, DialogHeader, DialogTitle, IconButton } from "@/components/ui";
import { DIALOG_WINDOW } from "@/lib/dialog-sizes";
import { partialArgs, type PartialField } from "@/lib/partial-args";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import {
  DEFAULT_HEIGHT,
  drewVisual,
  REVISE,
  framedElsewhere,
  inlineImages,
  isVisualTool,
  resolveVisual,
  streamedDrawing,
  svgAspect,
  type VisualKind,
  visualContentBase,
} from "@/lib/visuals";
import { getVisualImage, putVisualThumbnail } from "@/lib/visuals-api";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import {
  addVisualImages,
  resetVisualState,
  useSavedVisualsStore,
  useVisualImagesStore,
  useVisualStreamStore,
} from "@/stores/visual-stream-store";
import type { ChatMessage, ToolCall } from "@/types";
import { copySvgImage, downloadVisual, svgPng } from "./visual-actions";
import { VisualFrame } from "./visual-frame";
import { VisualSaveDialog } from "./visual-save-dialog";
import { VisualZoom } from "./visual-zoom";

type KnownCalls = ReadonlyMap<string, ToolCall>;

interface ConversationVisualsValue {
  /** Every visual call in the conversation on screen, which a revision is rebuilt from. */
  known: KnownCalls;
  /** The conversation, for saving a visual from it; null on a surface that cannot. */
  conversationId: string | null;
  /** Tell the running turn how one of its drawings rendered. */
  onReport?: (callId: string, errors: string[]) => void;
  /** Put a message in the composer, for the person to finish and send. */
  onCompose?: (text: string) => void;
}

const ConversationVisuals = createContext<ConversationVisualsValue>({
  known: new Map(),
  conversationId: null,
});

export function ConversationVisualsProvider({
  messages,
  conversationId,
  onReport,
  onCompose,
  children,
}: {
  messages: readonly ChatMessage[];
  conversationId: string | null;
  onReport?: (callId: string, errors: string[]) => void;
  onCompose?: (text: string) => void;
  children: React.ReactNode;
}) {
  const known = useMemo(() => {
    const calls = new Map<string, ToolCall>();
    for (const message of messages) {
      for (const call of message.toolCalls ?? []) {
        if (isVisualTool(call.name)) calls.set(call.id, call);
      }
    }
    return calls;
  }, [messages]);
  const value = useMemo(
    () => ({ known, conversationId, onReport, onCompose }),
    [known, conversationId, onReport, onCompose],
  );
  // Another thread on screen: the visual stores are keyed by the provider's call
  // id, which that thread may reuse. Not on a new thread learning its id
  // mid-turn, which would drop the pictures of the drawing being made.
  const shownFor = useRef(conversationId);
  useEffect(() => {
    if (shownFor.current !== null && conversationId !== shownFor.current) resetVisualState();
    shownFor.current = conversationId;
  }, [conversationId]);
  return <ConversationVisuals.Provider value={value}>{children}</ConversationVisuals.Provider>;
}

/** A turn's drawings, each a panel under the message where the turn made it. */
export function TurnVisuals({ calls }: { calls: ToolCall[] }) {
  if (calls.length === 0) return null;
  return (
    <div className="flex w-full min-w-0 flex-col gap-3 py-1">
      {calls.map((call) => (
        <VisualPanel key={call.id} call={call} />
      ))}
    </div>
  );
}

interface Shown {
  title: string;
  kind: VisualKind;
  content: string;
  height: number;
  done: boolean;
  /** The title of the visual this one revises; null for a drawing. */
  revisionOf: string | null;
  /** The ids this visual is built from, itself first - for the app it was saved as. */
  lineage: string[];
  /** Each picture the visual uses, by name, and the call that brought it. */
  images: Record<string, string>;
}

function fieldsOf(
  streamed: string | Record<string, unknown> | undefined,
): Record<string, PartialField> {
  if (streamed === undefined) return {};
  if (typeof streamed === "string") return partialArgs(streamed);
  return Object.fromEntries(
    Object.entries(streamed).map(([key, value]) => [key, { value, complete: true }]),
  );
}

function lineageOf(call: ToolCall, known: KnownCalls): string[] {
  const ids: string[] = [];
  let current: ToolCall | undefined = call;
  while (current !== undefined && ids.length < 50) {
    ids.push(current.id);
    const base: unknown = current.name === REVISE ? current.args.visual_id : undefined;
    current = typeof base === "string" ? known.get(base) : undefined;
  }
  return ids;
}

/**
 * What a call shows now: the finished visual once its arguments are in, and
 * before that whatever of it has streamed - for a revision, the visual it is
 * revising, until its edits are complete.
 */
function useShown(call: ToolCall, known: KnownCalls): Shown | null | "missing" {
  const streamed = useVisualStreamStore((state) => state.args[call.id]);
  return useMemo(() => {
    const arrived = Object.keys(call.args).length > 0;
    const revision = call.name === REVISE;
    if (arrived) {
      const visual = resolveVisual(call, known);
      if (visual === null) return revision ? "missing" : null;
      const base = revision ? known.get(String(call.args.visual_id)) : undefined;
      return {
        ...visual,
        done: call.status === "running" || call.status === "completed",
        revisionOf: base ? (resolveVisual(base, known)?.title ?? null) : null,
        lineage: lineageOf(call, known),
      };
    }
    const fields = fieldsOf(streamed);
    if (revision) {
      const id = fields.visual_id?.complete ? fields.visual_id.value : undefined;
      const base = typeof id === "string" ? known.get(id) : undefined;
      const visual = base ? resolveVisual(base, known) : null;
      return visual ? { ...visual, done: false, revisionOf: visual.title, lineage: [] } : null;
    }
    const drawing = streamedDrawing(fields);
    if (drawing.kind === null) return null;
    return {
      title: drawing.title,
      kind: drawing.kind,
      content: drawing.content,
      height: drawing.height ?? DEFAULT_HEIGHT,
      done: false,
      revisionOf: null,
      lineage: [],
      images: {},
    };
  }, [call, known, streamed]);
}

const NO_IMAGES: Record<string, string> = {};

/** Whether a page can change frames under it within its life: it cannot. */
const subscribeToNothing = () => () => {};

/** How wide a dashboard thumbnail is drawn. */
const THUMBNAIL_WIDTH = 640;

/**
 * Keep a thumbnail of a drawing this console just rendered, for its dashboard tile.
 *
 * Best effort by design: a drawing with no thumbnail is shown on the dashboard
 * by its kind's icon, so a refusal here costs a picture, not the drawing.
 */
function keepThumbnail(conversationId: string, visualId: string, svg: string): void {
  void svgPng(svg, THUMBNAIL_WIDTH)
    .then((png) => putVisualThumbnail(conversationId, visualId, png))
    .catch(() => undefined);
}

/** How many times a picture is asked for before the drawing is shown without it. */
const IMAGE_ATTEMPTS = 3;

/**
 * The pictures a finished visual uses, as `data:` URIs, and whether it may be drawn.
 *
 * A drawing made in this turn has its pictures already - the socket sent them
 * before the call was rendered. One read back from the transcript asks the image
 * route for each. A picture that cannot be had after a few attempts is left out
 * rather than holding the drawing back for ever.
 */
function useVisualImages(
  conversationId: string | null,
  wanted: Record<string, string>,
  done: boolean,
): { uris: Record<string, string>; ready: boolean } {
  const stored = useVisualImagesStore((state) => state.images);
  const [gaveUp, setGaveUp] = useState(false);
  const uris: Record<string, string> = {};
  const missing: [string, string][] = [];
  for (const [name, owner] of Object.entries(wanted)) {
    const uri = stored[owner]?.[name];
    if (uri !== undefined) uris[name] = uri;
    else missing.push([name, owner]);
  }
  // A string, so the effect below runs when the set of missing pictures changes
  // rather than on every render's fresh array.
  const key = JSON.stringify(missing);
  useEffect(() => {
    const pending = JSON.parse(key) as [string, string][];
    if (!done || conversationId === null || pending.length === 0) return;
    let cancelled = false;
    void (async () => {
      for (const [name, owner] of pending) {
        for (let attempt = 0; attempt < IMAGE_ATTEMPTS && !cancelled; attempt += 1) {
          try {
            addVisualImages(owner, { [name]: await getVisualImage(conversationId, owner, name) });
            break;
          } catch {
            await new Promise((resolve) => setTimeout(resolve, 1000));
          }
        }
      }
      if (!cancelled) setGaveUp(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId, key, done]);
  return { uris, ready: missing.length === 0 || gaveUp };
}

/**
 * Where the zoom sits: over the drawing's bottom right corner, shown only while
 * the pointer is on the card or a zoom button has focus, so it covers nothing
 * the rest of the time.
 */
const ZOOM_CORNER =
  "border-border bg-background/90 absolute right-2 bottom-2 rounded-full border shadow-sm backdrop-blur opacity-0 transition-opacity group-hover/visual:opacity-100 focus-within:opacity-100";

/** How many of a drawing's errors the panel lists; the first few say what broke. */
const SHOWN_ERRORS = 3;

/**
 * Saving publishes an app, which `artifacts:edit` decides: offered only to whoever
 * has it. A component of its own so that a thread shared by link, read signed
 * out, never asks for the reader's permissions.
 */
function SaveToApps({ update, onSave }: { update: boolean; onSave: () => void }) {
  const t = useTranslations("chat.visuals");
  const mayPublish = usePermissions().can(Perm.artifactsEdit);
  if (!mayPublish) return null;
  const label = update ? t("updateApp") : t("saveToApps");
  return (
    <IconButton aria-label={label} title={label} onClick={onSave}>
      <AppWindow className="size-4" />
    </IconButton>
  );
}

function VisualPanel({ call }: { call: ToolCall }) {
  const t = useTranslations("chat.visuals");
  const { known, conversationId, onReport, onCompose } = useContext(ConversationVisuals);
  const { artifactUrl } = usePublicConfig();
  const shown = useShown(call, known);
  const nested = useSyncExternalStore(subscribeToNothing, framedElsewhere, () => false);
  const pictures = useVisualImages(
    conversationId,
    shown !== null && shown !== "missing" ? shown.images : NO_IMAGES,
    shown !== null && shown !== "missing" && shown.done,
  );
  const saved = useSavedVisualsStore((state) => state.saved);
  const [code, setCode] = useState(false);
  const [full, setFull] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [fullZoom, setFullZoom] = useState(1);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [stalled, setStalled] = useState(false);
  const [frameKey, setFrameKey] = useState(0);
  // Read when the frame says it has rendered, which can be the same tick as the
  // last error - so a ref, not the state that has not re-rendered yet.
  const errorsSeen = useRef<string[]>([]);
  const reported = useRef(false);
  const thumbnailed = useRef(false);

  if (call.status === "error") return null;
  // Finished without drawing - the tool refused it - is no visual, whatever the
  // arguments held; a result still on its way is not a refusal yet.
  if (call.status === "completed" && call.result !== undefined && !drewVisual(call.result)) {
    return null;
  }
  const streaming =
    call.status === "pending" || (shown !== null && shown !== "missing" && !shown.done);
  if (shown === null) {
    return streaming ? <DrawingPlaceholder label={t("drawing")} /> : null;
  }
  if (shown === "missing") {
    return (
      <div className="text-muted-foreground bg-foreground/[0.04] max-w-2xl rounded-2xl px-3 py-2 text-sm">
        {t("baseMissing")}
      </div>
    );
  }
  if (nested) return <VisualCard title={shown.title} kind={shown.kind} content={shown.content} />;
  const unfinished = call.status === "unfinished";
  // Held back until its pictures are here: once its scripts run, a drawing is
  // not written again, and one drawn without them would stay without them.
  const done = shown.done && !unfinished && pictures.ready;
  const content = inlineImages(shown.content, pictures.uris);
  const app = shown.lineage.map((id) => saved[id]).find((entry) => entry !== undefined);
  const savedHere = saved[call.id];
  const label = unfinished
    ? t("unfinished")
    : !shown.done
      ? call.name === REVISE
        ? t("revising")
        : t("drawing")
      : shown.revisionOf !== null
        ? t("revisionOf", { title: shown.revisionOf })
        : null;

  const reload = () => {
    setStalled(false);
    setErrors([]);
    errorsSeen.current = [];
    setFrameKey((key) => key + 1);
  };
  const onError = (message: string) => {
    if (errorsSeen.current.includes(message)) return;
    errorsSeen.current = [...errorsSeen.current, message];
    setErrors(errorsSeen.current.slice(0, SHOWN_ERRORS));
  };
  // Once, and only while the call is still waiting: a drawing reloaded from the
  // transcript has nobody left to tell.
  const onRendered = () => {
    if (reported.current || call.status !== "running") return;
    reported.current = true;
    onReport?.(call.id, errorsSeen.current);
  };
  // Once, from the session that watched it being drawn: a drawing read back
  // later already has one, or never will from here.
  const onSvg = (markup: string) => {
    if (thumbnailed.current || call.status !== "running" || conversationId === null) return;
    if (shown.kind === "html") return;
    thumbnailed.current = true;
    keepThumbnail(conversationId, call.id, shown.kind === "svg" ? content : markup);
  };
  const copyImage = async () => {
    try {
      await copySvgImage(content);
      toast.success(t("imageCopied"));
    } catch {
      toast.error(t("copyImageFailed"));
    }
  };

  return (
    <div
      data-tour="chat-visual"
      className="group/visual border-border bg-background w-full max-w-2xl min-w-0 overflow-hidden rounded-2xl border shadow-sm"
    >
      <div className="border-border flex min-w-0 items-center gap-2 border-b py-1.5 pr-1.5 pl-3">
        <Shapes className="text-muted-foreground size-4 shrink-0" aria-hidden />
        <span className="text-foreground min-w-0 truncate text-sm font-medium">{shown.title}</span>
        {label !== null && (
          <span
            className={cn(
              "text-muted-foreground min-w-0 truncate text-xs",
              !shown.done && !unfinished && "shimmer-text",
            )}
          >
            {label}
          </span>
        )}
        {savedHere && (
          <Link
            href={savedHere.url}
            className="bg-foreground/[0.06] text-foreground hover:bg-foreground/10 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
          >
            {t("savedBadge", { version: savedHere.version })}
          </Link>
        )}
        <div className="ml-auto flex shrink-0 items-center">
          <IconButton
            aria-label={code ? t("showVisual") : t("showCode")}
            title={code ? t("showVisual") : t("showCode")}
            onClick={() => setCode((value) => !value)}
          >
            {code ? <Shapes className="size-4" /> : <Code2 className="size-4" />}
          </IconButton>
          {done && shown.kind === "svg" && (
            <IconButton aria-label={t("copyImage")} title={t("copyImage")} onClick={copyImage}>
              <Copy className="size-4" />
            </IconButton>
          )}
          {done && (
            <IconButton
              aria-label={t("download")}
              title={t("download")}
              onClick={() =>
                downloadVisual(
                  shown.title,
                  shown.kind,
                  content,
                  new URL(visualContentBase(artifactUrl), window.location.href).href,
                )
              }
            >
              <Download className="size-4" />
            </IconButton>
          )}
          {done && conversationId !== null && (
            <SaveToApps update={app !== undefined} onSave={() => setSaving(true)} />
          )}
          <IconButton
            aria-label={t("fullScreen")}
            title={t("fullScreen")}
            onClick={() => setFull(true)}
          >
            <Maximize2 className="size-4" />
          </IconButton>
        </div>
      </div>
      {code ? (
        <pre className="bg-foreground/[0.03] max-h-[32rem] scrollbar-thin overflow-auto p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
          {shown.content}
        </pre>
      ) : stalled ? (
        <div className="text-muted-foreground flex flex-col items-center gap-2 px-3 py-10 text-sm">
          {t("stalled")}
          <button
            type="button"
            onClick={reload}
            className="text-foreground inline-flex items-center gap-1.5 text-xs font-medium"
          >
            <RotateCw className="size-3.5" aria-hidden />
            {t("reload")}
          </button>
        </div>
      ) : (
        <div className="relative">
          <VisualFrame
            key={frameKey}
            kind={shown.kind}
            title={shown.title}
            content={content}
            done={done}
            height={shown.height}
            aspect={shown.kind === "svg" ? svgAspect(shown.content) : null}
            zoom={zoom}
            onError={onError}
            onRendered={onRendered}
            onSvg={onSvg}
            onStall={() => setStalled(true)}
          />
          {/* On a phone the preview is a picture: a drag on a canvas would take
              the scroll of the conversation with it, so a tap opens it full
              screen, where it is the whole window. */}
          <button
            type="button"
            aria-label={t("fullScreen")}
            onClick={() => setFull(true)}
            className="absolute inset-0 md:hidden"
          />
          {/* Not on a phone, where the preview is a picture that opens full
              screen, and zooming is done there. */}
          <VisualZoom zoom={zoom} onZoom={setZoom} className={cn(ZOOM_CORNER, "hidden md:flex")} />
        </div>
      )}
      {errors.length > 0 && (
        <div className="border-border flex items-start gap-2 border-t px-3 py-2 text-xs">
          <TriangleAlert className="text-destructive mt-0.5 size-3.5 shrink-0" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-foreground font-medium">{t("renderError")}</p>
            {errors.map((message) => (
              <p key={message} className="text-muted-foreground font-mono break-all">
                {message}
              </p>
            ))}
          </div>
          {onCompose && !streaming && (
            <button
              type="button"
              onClick={() =>
                onCompose(
                  t("fixItPrompt", { title: shown.title, id: call.id, errors: errors.join("\n") }),
                )
              }
              className="text-foreground hover:bg-foreground/[0.06] inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 font-medium"
            >
              <Wrench className="size-3.5" aria-hidden />
              {t("fixIt")}
            </button>
          )}
        </div>
      )}
      <Dialog open={full} onOpenChange={setFull}>
        <DialogContent className={DIALOG_WINDOW} aria-describedby={undefined}>
          <DialogHeader className="gap-0 pr-10">
            <DialogTitle className="truncate text-base">{shown.title}</DialogTitle>
          </DialogHeader>
          <div className="group/visual border-border relative min-h-0 flex-1 overflow-hidden rounded-xl border">
            {full && (
              <VisualFrame
                kind={shown.kind}
                title={shown.title}
                content={content}
                done={done}
                height={shown.height}
                zoom={fullZoom}
                fill
              />
            )}
            <VisualZoom zoom={fullZoom} onZoom={setFullZoom} className={ZOOM_CORNER} />
          </div>
        </DialogContent>
      </Dialog>
      {saving && conversationId !== null && (
        <VisualSaveDialog
          open
          onOpenChange={setSaving}
          conversationId={conversationId}
          visualId={call.id}
          title={shown.title}
          updates={app?.name ?? null}
        />
      )}
    </div>
  );
}

/**
 * A visual where its frame cannot be: its title, and an SVG as a picture.
 *
 * An SVG shown through `<img>` runs no script, so it is safe on any page; a page
 * or a diagram needs the frame, and is named rather than drawn.
 */
function VisualCard({
  title,
  kind,
  content,
}: {
  title: string;
  kind: VisualKind;
  content: string;
}) {
  const t = useTranslations("chat.visuals");
  return (
    <div className="border-border bg-background w-full max-w-2xl min-w-0 overflow-hidden rounded-2xl border">
      {kind === "svg" && (
        // A data URI the console made, which `next/image` has nothing to optimise.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(content)}`}
          alt={title}
          className="bg-background block max-h-[28rem] w-full object-contain"
        />
      )}
      <div className="flex min-w-0 items-center gap-2 px-3 py-2">
        <Shapes className="text-muted-foreground size-4 shrink-0" aria-hidden />
        <span className="text-foreground min-w-0 truncate text-sm font-medium">{title}</span>
        {kind !== "svg" && (
          <span className="text-muted-foreground ml-auto shrink-0 text-xs">
            {t("openInConsole")}
          </span>
        )}
      </div>
    </div>
  );
}

function DrawingPlaceholder({ label }: { label: string }) {
  return (
    <div className="border-border bg-background flex h-32 w-full max-w-2xl items-center justify-center rounded-2xl border">
      <span className="shimmer-text text-muted-foreground text-sm">{label}</span>
    </div>
  );
}
