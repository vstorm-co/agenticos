import { NextRequest, NextResponse } from "next/server";
import { bffRefusal } from "@/lib/server-api";

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
    const url = `${BACKEND_URL}/api/v1/files/${id}${qs ? `?${qs}` : ""}`;
    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });

    if (!response.ok) {
      return bffRefusal("FILE_NOT_FOUND", response.status);
    }

    const data = await response.arrayBuffer();
    const contentType = response.headers.get("content-type") || "application/octet-stream";
    const disposition = response.headers.get("content-disposition") || "";

    return new NextResponse(data, {
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": disposition,
        "Cache-Control": "private, max-age=3600",
        // Override the global X-Frame-Options: DENY from next.config.ts so
        // the chat file-preview panel can embed PDFs / HTML in an iframe
        // from the same origin. Without this, Firefox refuses to render.
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
      },
    });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
