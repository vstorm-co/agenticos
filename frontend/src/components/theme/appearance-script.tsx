import { headers } from "next/headers";

import { APPEARANCE_BOOTSTRAP_SCRIPT } from "@/lib/appearance";

/**
 * The no-flash half of the look and of the desktop app's layout: an inline
 * script in `<head>` that sets `data-look` and the shell's attributes on
 * `<html>` before anything paints (see `APPEARANCE_BOOTSTRAP_SCRIPT`).
 *
 * Nonced like `MotionScript`, for the same Content-Security-Policy, and
 * `suppressHydrationWarning` for the same blanked attribute.
 */
export async function AppearanceScript() {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <script
      nonce={nonce}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: APPEARANCE_BOOTSTRAP_SCRIPT }}
    />
  );
}
