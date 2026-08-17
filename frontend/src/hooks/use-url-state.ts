"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { setUrlParam } from "@/lib/utils";

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
