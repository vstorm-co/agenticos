"use client";

import { useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import { appHistoryState, HELD_ENTRY, OVERLAY_ENTRY, traverseHistory } from "@/lib/history-entries";
import { pushUrlParam, setUrlParam, setUrlParams } from "@/lib/utils";

/**
 * Page state mirrored into one query parameter.
 *
 * For a value that is both a control on the page and a hand-off other pages
 * link with - `?agent=` from the Builder, `?run=` from a delegation panel. The
 * setter updates the state and rewrites the URL; a navigation that changes the
 * parameter under the state wins, via the render-time adjustment React
 * documents (the parameter seen last is stored beside the value, and a fresh
 * one resets it) - never an effect, which would paint a stale frame first.
 */
export function useUrlState(key: string): [string | null, (value: string | null) => void] {
  const [value, show] = useParamValue(key);
  const set = (next: string | null) => {
    show(next);
    setUrlParam(key, next);
  };
  return [value, set];
}

/** The parameter's value, and a way to show a new one before the URL catches up. */
function useParamValue(key: string): [string | null, (value: string | null) => void] {
  const searchParams = useSearchParams();
  const param = searchParams.get(key);
  const [state, setState] = useState({ seenParam: param, value: param });
  if (state.seenParam !== param) {
    setState({ seenParam: param, value: param });
  }
  const value = state.seenParam === param ? state.value : param;
  return [value, (next) => setState({ seenParam: param, value: next })];
}

/** Opening and closing the object a `useUrlOverlay` parameter names. */
export interface UrlOverlay {
  /** Open `value`: a new history entry from the page, in place from another open object. */
  open: (value: string) => void;
  /** Close it: Back over the entry `open` pushed, or the parameter dropped in place. */
  close: () => void;
  /** Set or drop the parameter in place, adding no history entry. */
  replace: (value: string | null) => void;
}

/**
 * One object opened over its page - a case in its dataset, a run in Activity, a
 * gap topic - in a query parameter that is its own history entry.
 *
 * Going to another object is a step Back undoes, so opening one from the page
 * pushes an entry, and closing it takes that step back rather than adding a
 * second copy of the page; the browser's Back closes it the same way. Opened
 * from a link, there is no entry of ours to go back over, so closing drops the
 * parameter in place.
 */
export function useUrlOverlay(key: string): [string | null, UrlOverlay] {
  const [value, show] = useParamValue(key);
  // The object already being closed: a dialog can report closing twice before Back lands.
  const closing = useRef<string | null>(null);
  const replace = (next: string | null) => {
    show(next);
    setUrlParam(key, next);
  };
  const open = (next: string) => {
    closing.current = null;
    if (value !== null) return replace(next);
    show(next);
    pushUrlParam(key, next, { [OVERLAY_ENTRY]: key });
  };
  const close = () => {
    if (value === null || closing.current === value) return;
    const state = appHistoryState();
    if (state[OVERLAY_ENTRY] !== key) return replace(null);
    closing.current = value;
    show(null);
    // A guard's duplicate of this entry sits on top of it, and Back would land there.
    traverseHistory(state[HELD_ENTRY] ? -2 : -1);
  };
  return [value, { open, close, replace }];
}

/**
 * A query parameter that repeats (`?outcome=a&outcome=b`), as the same kind of page
 * state: the values as they stand, and a setter that rewrites every occurrence.
 * A link such as a log alert's carries several, so the one-value form would read
 * only the first.
 */
export function useUrlList(key: string): [string[], (values: string[]) => void] {
  const searchParams = useSearchParams();
  const param = searchParams.getAll(key);
  const seen = param.join("\n");
  const [state, setState] = useState({ seen, values: param });
  if (state.seen !== seen) {
    setState({ seen, values: param });
  }
  const values = state.seen === seen ? state.values : param;
  const set = (next: string[]) => {
    setState({ seen, values: next });
    setUrlParams(key, next);
  };
  return [values, set];
}
