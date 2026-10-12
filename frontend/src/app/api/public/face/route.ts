import { readFile } from "node:fs/promises";
import path from "node:path";

import { _parts, serializeVars } from "blobatar/internal";
import { thinking } from "blobatar/expression";

import { avatarHue } from "@/lib/avatar-color";

/**
 * An agent's drawn face as a self-contained SVG image, for the website widget (#2006).
 *
 * The widget runs on somebody else's page with no dependencies, so it cannot run
 * the generator the console draws faces with; it shows this as an `<img>`. The
 * motion stylesheet travels inside the SVG, because no stylesheet reaches into an
 * image - so the face still blinks, breathes and, with `thinking=1`, ponders, and
 * still holds still under `prefers-reduced-motion`.
 *
 * Public and uncached per person: it draws from a handle, which the widget's
 * config already names, and reads nothing.
 */

// Read once per server, from the package, rather than copied into this file.
let motionCss: Promise<string> | null = null;
function motion(): Promise<string> {
  motionCss ??= readFile(path.join(process.cwd(), "node_modules/blobatar/dist/motion.css"), "utf8");
  return motionCss;
}

const SEED_LIMIT = 64;

export async function GET(request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const seed = (params.get("seed") ?? "").slice(0, SEED_LIMIT);
  if (!seed) return new Response(null, { status: 404 });
  const slot = Number(params.get("slot"));
  const parts = _parts(seed, {
    background: "circle",
    hue: avatarHue(Number.isInteger(slot) ? slot : null),
    animate: "always",
    expression: params.get("thinking") === "1" ? thinking : undefined,
  });
  const backdrop = parts.bg ? `<path d="${parts.bg.d}" fill="${parts.bg.fill}"/>` : "";
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" class="${parts.cls ?? ""}"` +
    // CDATA, because the stylesheet declares `syntax: "<number>"` and an image
    // is parsed as XML, where that is a tag that never closes.
    ` style="${serializeVars(parts.vars ?? {})}"><style><![CDATA[${await motion()}]]></style>` +
    `${backdrop}${parts.inner}</svg>`;
  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      // The same handle draws the same face for as long as this major of the
      // generator ships, so a day is safe and spares a stranger's page a request.
      "Cache-Control": "public, max-age=86400",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
