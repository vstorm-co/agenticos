"use client";

import { create } from "zustand";

/**
 * A visual's arguments as they arrive, by tool call id, until the call itself does.
 *
 * Only the calls that draw: every other tool's arguments are dropped on arrival,
 * as they always were - writing a `write_file` report into a store on every frame
 * re-rendered the whole turn hundreds of times a second. Even these are not
 * written per delta: the text gathers here outside React and is published at
 * most every `FLUSH_MS`, which is as often as the frame redraws anyway.
 *
 * Keyed by call id rather than scoped per chat, and cleared whenever another
 * conversation, tenant or account takes the screen - see `resetVisualState`.
 */
interface VisualStreamState {
  /** The JSON text so far, or the object so far when a provider streams objects. */
  args: Record<string, string | Record<string, unknown>>;
}

const FLUSH_MS = 100;

export const useVisualStreamStore = create<VisualStreamState>()(() => ({ args: {} }));

const pending = new Map<string, string | Record<string, unknown>>();
let timer: ReturnType<typeof setTimeout> | null = null;

function flush() {
  timer = null;
  if (pending.size === 0) return;
  const next = { ...useVisualStreamStore.getState().args };
  for (const [id, value] of pending) next[id] = value;
  pending.clear();
  useVisualStreamStore.setState({ args: next });
}

/**
 * Add one `tool_call_delta` to a call's arguments.
 *
 * A string is more of the JSON text. An object is how some providers stream
 * instead, and each one replaces the keys it names - the way Pydantic AI itself
 * merges an object delta into the part.
 */
export function appendVisualArgs(callId: string, delta: unknown): void {
  const current = pending.get(callId) ?? useVisualStreamStore.getState().args[callId];
  if (typeof delta === "string") {
    pending.set(callId, (typeof current === "string" ? current : "") + delta);
  } else if (typeof delta === "object" && delta !== null && !Array.isArray(delta)) {
    const base = typeof current === "object" ? current : {};
    pending.set(callId, { ...base, ...(delta as Record<string, unknown>) });
  } else {
    return;
  }
  timer ??= setTimeout(flush, FLUSH_MS);
}

/** Forget a call's streamed arguments: the finished call carries its own. */
export function dropVisualArgs(callId: string): void {
  pending.delete(callId);
  const { args } = useVisualStreamStore.getState();
  if (!(callId in args)) return;
  const next = { ...args };
  delete next[callId];
  useVisualStreamStore.setState({ args: next });
}

/** An app a visual was saved as in this session, for its badge and its revisions. */
export interface SavedVisual {
  artifactId: string;
  name: string;
  version: number;
  url: string;
}

interface SavedVisualsState {
  saved: Record<string, SavedVisual>;
}

/**
 * Which visuals were saved as apps here, by visual id.
 *
 * Only what this tab did: a revision of a saved visual offers to update that
 * app rather than make a second one. A reload forgets it, and the name is then
 * typed again - the server still adds a version to an app of that name.
 */
export const useSavedVisualsStore = create<SavedVisualsState>()(() => ({ saved: {} }));

export function rememberSavedVisual(visualId: string, app: SavedVisual): void {
  useSavedVisualsStore.setState((state) => ({ saved: { ...state.saved, [visualId]: app } }));
}

interface VisualImagesState {
  /** Each visual's images as `data:` URIs, by the visual's id and the image's name. */
  images: Record<string, Record<string, string>>;
}

/**
 * The pictures drawings use, once they are here.
 *
 * Filled two ways: by the socket while a turn draws (the transcript records the
 * call only when the turn ends, so there is nothing to ask for yet), and by the
 * image route for a drawing read back from the transcript.
 */
export const useVisualImagesStore = create<VisualImagesState>()(() => ({ images: {} }));

export function addVisualImages(visualId: string, images: Record<string, string>): void {
  useVisualImagesStore.setState((state) => ({
    images: { ...state.images, [visualId]: { ...state.images[visualId], ...images } },
  }));
}

/**
 * Forget every visual's streamed arguments, pictures and saved app.
 *
 * All three are keyed by tool-call id, which is the model provider's to choose: a
 * local model may number its calls `call_0`, `call_1` in every conversation, so
 * what one thread - or another organization - held would otherwise be shown in
 * the next. Called when the tenant or the account changes, and when another
 * conversation takes the screen.
 */
export function resetVisualState(): void {
  pending.clear();
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
  useVisualStreamStore.setState({ args: {} });
  useSavedVisualsStore.setState({ saved: {} });
  useVisualImagesStore.setState({ images: {} });
}
