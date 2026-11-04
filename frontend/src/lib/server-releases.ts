import { version } from "../../package.json";
import { unstable_cache } from "next/cache";
import { parseVersion, type AppRelease, type ReleaseNotes } from "@/lib/releases";

const RELEASE_API = "https://api.github.com/repos/vstorm-co/agenticos/releases/latest";
interface GithubRelease {
  tag_name: string;
  draft: boolean;
  prerelease: boolean;
  body?: string | null;
}

function isRelease(value: unknown): value is GithubRelease {
  return (
    typeof value === "object" &&
    value !== null &&
    "tag_name" in value &&
    typeof value.tag_name === "string" &&
    "draft" in value &&
    typeof value.draft === "boolean" &&
    "prerelease" in value &&
    typeof value.prerelease === "boolean" &&
    (!("body" in value) || value.body === null || typeof value.body === "string")
  );
}

type ReleaseCheck = { ok: true; latest: AppRelease | null } | { ok: false };

/** Only public release metadata leaves this boundary; no cookies or tenant headers are forwarded. */
async function fetchRelease(
  url: string,
): Promise<{ ok: true; release: GithubRelease | null } | { ok: false }> {
  try {
    const response = await fetch(url, {
      headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10" },
      credentials: "omit",
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (response.status === 404) return { ok: true, release: null };
    if (!response.ok) return { ok: false };
    const payload: unknown = await response.json();
    if (!isRelease(payload) || payload.draft || payload.prerelease) return { ok: false };
    const version = parseVersion(payload.tag_name);
    if (!version || version.prerelease) return { ok: false };
    return { ok: true, release: payload };
  } catch (error) {
    if (
      error instanceof TypeError ||
      error instanceof SyntaxError ||
      (error instanceof DOMException && ["AbortError", "TimeoutError"].includes(error.name))
    )
      return { ok: false };
    throw error;
  }
}

function releaseSummary(release: GithubRelease): AppRelease {
  return {
    version: release.tag_name.replace(/^v/, ""),
    url: `https://github.com/vstorm-co/agenticos/releases/tag/${encodeURIComponent(release.tag_name)}`,
  };
}

export async function fetchLatestRelease(): Promise<ReleaseCheck> {
  const result = await fetchRelease(RELEASE_API);
  return result.ok
    ? { ok: true, latest: result.release ? releaseSummary(result.release) : null }
    : result;
}

export async function fetchCurrentRelease(): Promise<
  { ok: true; release: ReleaseNotes | null } | { ok: false }
> {
  if (!parseVersion(version)) return { ok: true, release: null };
  const result = await fetchRelease(
    `https://api.github.com/repos/vstorm-co/agenticos/releases/tags/v${encodeURIComponent(version)}`,
  );
  if (!result.ok) return result;
  const release = result.release;
  if (!release || typeof release.body !== "string" || !release.body.trim())
    return { ok: true, release: null };
  const summary = releaseSummary(release);
  if (summary.version !== version) return { ok: false };
  return { ok: true, release: { ...summary, body: release.body.slice(0, 40_000) } };
}

export const currentRelease = unstable_cache(
  fetchCurrentRelease,
  ["agenticos-release-notes", version],
  { revalidate: 300 },
);

/** Share both successful and unavailable checks across users, limiting public GitHub requests. */
export const latestRelease = unstable_cache(
  fetchLatestRelease,
  ["agenticos-latest-stable-release"],
  { revalidate: 300 },
);
