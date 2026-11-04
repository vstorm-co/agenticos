import { latestRelease } from "@/lib/server-releases";
import { bffJson, bffRefusal } from "@/lib/server-api";

/** Public, cached upstream release metadata; no deployment or account data is sent. */
export async function GET() {
  const result = await latestRelease();
  return result.ok
    ? bffJson({ latest: result.latest })
    : bffRefusal("RELEASE_CHECK_UNAVAILABLE", 503);
}
