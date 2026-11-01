"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { setUrlParam, setUrlParams } from "@/lib/utils";

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
  const searchParams = useSearchParams();
  const param = searchParams.get(key);
  const [state, setState] = useState({ seenParam: param, value: param });
  if (state.seenParam !== param) {
    setState({ seenParam: param, value: param });
  }
  const value = state.seenParam === param ? state.value : param;
  const set = (next: string | null) => {
    setState({ seenParam: param, value: next });
    setUrlParam(key, next);
  };
  return [value, set];
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
