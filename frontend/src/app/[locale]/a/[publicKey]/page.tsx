import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PublicArtifact } from "@/components/artifacts/public-artifact";
import type { PublicArtifact as PublicArtifactData } from "@/types/artifact";

/**
 * An artifact behind its "anyone with the link" address.
 *
 * Outside `(dashboard)` for the reason `/e/[publicKey]` is: no session, no
 * organization, none of the console. The answer is fetched server-side, so the
 * signed content address the frame loads is minted per visit and never cached.
 */
interface PublicArtifactPageProps {
  params: Promise<{ publicKey: string; locale: string }>;
}

/** One request per visit, shared by the metadata and the render. */
const fetchPublicArtifact = cache(async (publicKey: string): Promise<PublicArtifactData | null> => {
  // `secrets.token_urlsafe` minted the key, so anything outside its alphabet
  // is not one this deployment made.
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(publicKey)) return null;
  const baseUrl = process.env.BACKEND_URL || "http://localhost:8000";
  const response = await fetch(
    `${baseUrl}/api/v1/public/artifacts/${encodeURIComponent(publicKey)}`,
    { cache: "no-store" },
  );
  // A revoked, rotated or never-made key are one answer. Anything else - a
  // backend restarting, the per-link limit - is not the page being gone, so it
  // reaches the error boundary instead of telling a reader the link is dead.
  if (response.status === 404) return null;
  if (!response.ok) {
    // i18n-exempt: an Error message for the boundary and the logs, never rendered copy.
    throw new Error(`Public artifact request failed with ${response.status}`);
  }
  return (await response.json()) as PublicArtifactData;
});

export async function generateMetadata({ params }: PublicArtifactPageProps): Promise<Metadata> {
  const { publicKey } = await params;
  const artifact = await fetchPublicArtifact(publicKey);
  return {
    title: artifact?.title ?? undefined,
    // The key is the whole of what protects the link; a crawler that followed
    // one would publish it.
    robots: { index: false, follow: false },
  };
}

export default async function PublicArtifactPage({ params }: PublicArtifactPageProps) {
  const { publicKey } = await params;
  const artifact = await fetchPublicArtifact(publicKey);
  if (artifact === null) notFound();
  return <PublicArtifact artifact={artifact} />;
}
