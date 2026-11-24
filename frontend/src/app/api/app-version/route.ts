import { getAppBuildId } from "@/lib/app-build";

export const dynamic = "force-dynamic";

/** Public deployment metadata, with no account or application data. */
export function GET(): Response {
  return Response.json(
    { buildId: getAppBuildId() },
    { headers: { "Cache-Control": "no-store, max-age=0" } },
  );
}
