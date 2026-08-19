/**
 * Serving the deployment's logo and favicon through this app's origin.
 *
 * The bytes live behind the API, which in any real deployment is not on this
 * origin and is often not reachable from a browser at all - so a `<link
 * rel="icon">` or an `<img>` pointing at the backend's own address would simply
 * not load. This is the hop that fixes that, and it is one function rather than
 * two route files repeating it.
 *
 * It forwards the backend's `Content-Type` and `Cache-Control` untouched, which is
 * the whole point: the backend decided the media type from the stored file rather
 * than letting anything guess it, and its year-long `immutable` policy is safe
 * only because the `?v=` in the address changes when the image does. Re-deciding
 * either here would undo one of those.
 *
 * No session. A browser fetching a favicon sends no cookie this app would read,
 * and the image is the deployment's public mark.
 */

import { NextResponse } from "next/server";

import { bffRefusal } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const DESCRIBES_THE_BODY = ["content-type", "cache-control"];

export async function proxyBrandingImage(
  kind: "logo" | "favicon",
  search: string,
): Promise<Response> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/branding/${kind}${search}`, {
      cache: "no-store",
    });
    // 404 is the ordinary answer for a deployment using the built-in mark, so it
    // is forwarded as itself rather than turned into a failure.
    if (!response.ok) {
      return new NextResponse(null, { status: response.status });
    }
    const headers = new Headers();
    for (const name of DESCRIBES_THE_BODY) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    headers.set("X-Content-Type-Options", "nosniff");
    return new NextResponse(await response.arrayBuffer(), { status: 200, headers });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
