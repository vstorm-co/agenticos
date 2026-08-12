import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { HostedChat } from "@/components/hosted/hosted-chat";
import type { HostedPageConfig } from "@/types/hosted";

/**
 * A published agent, reached by a link and nothing else.
 *
 * Outside `(dashboard)` on purpose: no session, no organization header and none
 * of the console shell. Beside `/shared/[token]`, which is the other page this
 * product serves to somebody who is not a member - that one opens a conversation
 * somebody already had, and this one is a conversation with an agent.
 *
 * The config is fetched **server-side**, which is also what makes the browser's
 * first paint the branded one rather than a flash of nothing. It reaches the
 * backend directly, so it sends no `Origin` and needs none: the hosted endpoint
 * does not check one, because an allow-list is a rule about other people's sites
 * and this page is ours.
 */
interface HostedPageProps {
  params: Promise<{ publicKey: string; locale: string }>;
}

/**
 * Wrapped in `cache` so the title and the page are one request, not two.
 *
 * `generateMetadata` and the render both need the config, and both run for the
 * same visit - so without this the backend is asked twice for every page load.
 * That doubled the only route whose limit is counted per page rather than per
 * address, and it left a second failure open: the metadata could be answered and
 * the render refused, which renders a titled 404.
 */
const fetchHostedConfig = cache(async (publicKey: string): Promise<HostedPageConfig | null> => {
  // The key is generated with `secrets.token_urlsafe`, so anything outside that
  // alphabet is not a key this deployment ever minted.
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(publicKey)) return null;
  const baseUrl = process.env.BACKEND_URL || "http://localhost:8000";
  const response = await fetch(`${baseUrl}/api/v1/embed/${encodeURIComponent(publicKey)}/hosted`, {
    cache: "no-store",
  });
  if (!response.ok) return null;
  const config = (await response.json()) as Omit<HostedPageConfig, "public_key">;
  return { ...config, public_key: publicKey };
});

export async function generateMetadata({ params }: HostedPageProps): Promise<Metadata> {
  const { publicKey } = await params;
  const config = await fetchHostedConfig(publicKey);
  return {
    title: config?.title ?? undefined,
    // A secret link is not a page to be indexed, and the key is the whole of
    // what protects it - a crawler that follows one published it.
    robots: { index: false, follow: false },
  };
}

export default async function HostedPage({ params }: HostedPageProps) {
  const { publicKey } = await params;
  const config = await fetchHostedConfig(publicKey);

  // 404 for a key that names nothing and for one whose page is not published -
  // the same amount of information, which is none.
  if (config === null) notFound();

  return <HostedChat config={config} />;
}
