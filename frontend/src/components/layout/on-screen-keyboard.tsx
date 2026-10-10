"use client";

import { useOnScreenKeyboard } from "@/hooks/use-on-screen-keyboard";

/** Mounts {@link useOnScreenKeyboard} under a server-rendered layout. */
export function OnScreenKeyboard() {
  useOnScreenKeyboard();
  return null;
}
