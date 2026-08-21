import { NextRequest, NextResponse } from "next/server";
import { bffRefusal } from "@/lib/server-api";
import { RENDER_SAFE_TYPES, baseContentType } from "@/lib/proxy-content-type";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) {
      return bffRefusal("NOT_AUTHENTICATED", 401);
    }

    // Forward ?disposition=attachment so the explicit Download button can
    // force a save dialog. Default (inline) lets the preview iframe render.
    const qs = request.nextUrl.searchParams.toString();
    const url = `${BACKEND_URL}/api/v1/files/${encodeURIComponent(id)}${qs ? `?${qs}` : ""}`;
    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });

    if (!response.ok) {
      return bffRefusal("FILE_NOT_FOUND", response.status);
    }

    const data = await response.arrayBuffer();
    const contentType =
      baseContentType(response.headers.get("content-type")) || "application/octet-stream";
    const disposition = response.headers.get("content-disposition") || "";

    // Unlike the avatars, this route serves PDFs, spreadsheets and text on
    // purpose, so it cannot refuse a non-image. What it must not do is render a
    // type that could execute on this origin: a stored `text/html` or SVG is
    // forced to download rather than be shown inline (#702). Images and PDFs -
    // the render-safe set - keep whatever disposition the backend chose. A viewer
    // that reads the bytes itself (the text preview) is unaffected.
    const finalDisposition = RENDER_SAFE_TYPES.has(contentType) ? disposition : "attachment";

    return new NextResponse(data, {
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": finalDisposition,
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        // Override the global X-Frame-Options: DENY from next.config.ts so
        // the chat file-preview panel can embed PDFs in an iframe from the same
        // origin. Without this, Firefox refuses to render.
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
      },
    });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
