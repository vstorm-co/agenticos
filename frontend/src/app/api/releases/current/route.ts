import { currentRelease } from "@/lib/server-releases";
import { bffJson, bffRefusal } from "@/lib/server-api";
export async function GET() {
  const result = await currentRelease();
  return result.ok
    ? bffJson({ release: result.release })
    : bffRefusal("RELEASE_CHECK_UNAVAILABLE", 503);
}
