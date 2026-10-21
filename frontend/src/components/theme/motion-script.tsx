import { headers } from "next/headers";

import { MOTION_BOOTSTRAP_SCRIPT } from "@/lib/motion-preference";

/**
 * The no-flash half of the Motion preference: an inline script in `<head>` that
 * sets `data-motion="reduce"` on `<html>` before anything paints.
 *
 * It carries this request's nonce (`x-nonce`, set by `middleware.ts`), because
 * the Content-Security-Policy admits no inline script without it.
 * `suppressHydrationWarning` because browsers blank a nonce attribute once the
 * script has run, so the DOM never matches the server's markup on that one
 * attribute.
 */
export async function MotionScript() {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <script
      nonce={nonce}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: MOTION_BOOTSTRAP_SCRIPT }}
    />
  );
}
