"use client";

import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";

import {
  clampToArea,
  HOP_MS,
  nextBehaviour,
  QUIP_CHANCE,
  strollStep,
  type Area,
  type Behaviour,
  type BlobbyState,
  type Reaction,
} from "@/lib/desktop/blobby-engine";
import type { Chatter } from "@/lib/desktop/commands";
import { saveBlobbyPosition } from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";
import { currentWindow, type DesktopWindow } from "@/lib/desktop/window";

const SAVE_DELAY_MS = 400;
const GAZE_POLL_MS = 250;

interface Options {
  roams: boolean;
  chatter: Chatter;
  /** Held still: reduced motion, or nobody signed in. */
  still: boolean;
  /** Called when a change of behaviour comes with a quip. */
  onQuip: () => void;
}

export interface BlobbyMotion {
  state: BlobbyState;
  /** Which way it faces on a stroll: -1 left, 1 right. */
  facing: -1 | 1;
  /** Where the cursor is, in this page's coordinates, for the eyes to follow. */
  gaze: { x: number; y: number } | null;
  react: (reaction: Reaction, ms: number) => void;
  startDragging: () => void;
}

/**
 * Blobby's body: what it is doing, its window strolling along the bottom of the
 * screen, its eyes on the cursor, and where it was left, remembered.
 *
 * The behaviour runs on a frame loop so a stroll is smooth, and renders only
 * when the behaviour changes - not every frame - since a React render per frame
 * for a window that mostly stands still is a fan spinning for nothing.
 */
export function useBlobbyMotion({ roams, chatter, still, onQuip }: Options): BlobbyMotion {
  const [state, setState] = useState<BlobbyState>("idle");
  const [facing, setFacing] = useState<-1 | 1>(1);
  const [gaze, setGaze] = useState<{ x: number; y: number } | null>(null);
  const win = useRef<DesktopWindow | null>(null);
  const place = useRef<{ x: number; y: number } | null>(null);
  const size = useRef<{ width: number; height: number } | null>(null);
  const area = useRef<Area | null>(null);
  const behaviour = useRef<Behaviour>({ state: "idle", ms: 5000, dir: 1 });
  const behaviourStart = useRef(0);
  const reaction = useRef<{ state: Reaction; until: number } | null>(null);
  const dragging = useRef(false);
  // The next ambient behaviour, read with this render's settings from inside
  // the frame loop, which is not restarted when they change.
  const changeBehaviour = useEffectEvent((now: number) => {
    behaviour.current = nextBehaviour(Math.random, new Date().getHours(), roams);
    behaviourStart.current = now;
    setState(behaviour.current.state);
    setFacing(behaviour.current.dir);
    if (Math.random() < QUIP_CHANCE[chatter]) onQuip();
  });

  /** Where the window is, how big, and on which monitor - kept on it. Answers where it ends up. */
  const measure = useCallback(async (handle: DesktopWindow) => {
    const [position, measured, monitor] = await Promise.all([
      handle.position(),
      handle.size(),
      handle.monitorArea(),
    ]);
    size.current = measured;
    area.current = monitor;
    const inside = monitor ? clampToArea(position, measured, monitor) : position;
    place.current = inside;
    if (inside.x !== position.x || inside.y !== position.y) await handle.moveTo(inside);
    return inside;
  }, []);

  const react = useCallback((next: Reaction, ms: number) => {
    reaction.current = { state: next, until: performance.now() + ms };
    setState(next);
  }, []);

  const startDragging = useCallback(() => {
    dragging.current = true;
    win.current
      ?.startDragging()
      .catch((error: unknown) => reportShellFailure("could not drag blobby", error));
  }, []);

  // The window, and where it is kept.
  useEffect(() => {
    let handle: DesktopWindow;
    try {
      handle = currentWindow();
    } catch (error) {
      reportShellFailure("blobby has no window", error);
      return;
    }
    win.current = handle;
    let saveTimer: ReturnType<typeof setTimeout> | undefined;
    let stop: (() => void) | undefined;
    let gone = false;
    measure(handle).catch((error: unknown) => reportShellFailure("could not place blobby", error));
    handle
      .onMoved((point) => {
        place.current = point;
        clearTimeout(saveTimer);
        // Once the window has come to rest: re-measure - it may be on another
        // monitor now - then save, and land a drag with a hop.
        saveTimer = setTimeout(() => {
          measure(handle)
            .then((rest) => saveBlobbyPosition(rest.x, rest.y))
            .catch((error: unknown) => reportShellFailure("could not keep blobby's place", error));
          if (dragging.current) {
            dragging.current = false;
            react("hop", HOP_MS);
          }
        }, SAVE_DELAY_MS);
      })
      .then((unlisten) => {
        if (gone) unlisten();
        else stop = unlisten;
      })
      .catch((error: unknown) => reportShellFailure("could not follow blobby's window", error));
    return () => {
      gone = true;
      clearTimeout(saveTimer);
      stop?.();
    };
  }, [measure, react]);

  // What it does when nobody is touching it.
  useEffect(() => {
    if (still) return;
    let frame = 0;
    let last = performance.now();
    behaviourStart.current = last;
    const tick = (now: number) => {
      const dt = now - last;
      last = now;
      if (reaction.current && now >= reaction.current.until) {
        reaction.current = null;
        setState(behaviour.current.state);
      }
      if (!reaction.current && now - behaviourStart.current >= behaviour.current.ms) {
        changeBehaviour(now);
      }
      const walking =
        !reaction.current && !dragging.current && behaviour.current.state === "stroll";
      if (walking && win.current && place.current && size.current && area.current) {
        const step = strollStep(
          place.current.x,
          behaviour.current.dir,
          dt,
          area.current.x,
          area.current.x + area.current.width - size.current.width,
        );
        if (step.dir !== behaviour.current.dir) {
          behaviour.current = { ...behaviour.current, dir: step.dir };
          setFacing(step.dir);
        }
        place.current = { x: step.x, y: place.current.y };
        win.current
          .moveTo(place.current)
          .catch((error: unknown) => reportShellFailure("could not walk blobby", error));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [still]);

  // The eyes follow the cursor while it stands about; asleep or walking, they do not.
  useEffect(() => {
    if (still) return;
    const timer = setInterval(() => {
      const handle = win.current;
      const here = place.current;
      if (!handle || !here || behaviour.current.state !== "idle" || reaction.current) {
        setGaze(null);
        return;
      }
      handle
        .cursor()
        .then((cursor) => setGaze({ x: cursor.x - here.x, y: cursor.y - here.y }))
        .catch((error: unknown) => reportShellFailure("could not find the cursor", error));
    }, GAZE_POLL_MS);
    return () => clearInterval(timer);
  }, [still]);

  // Held still, it stands: a stroll or a doze it was in stops with the loop.
  // A reaction still shows - a click is answered either way.
  const ambient = state === "stroll" || state === "doze";
  return { state: still && ambient ? "idle" : state, facing, gaze, react, startDragging };
}
