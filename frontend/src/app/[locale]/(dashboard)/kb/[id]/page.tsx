import { redirect } from "next/navigation";

import { ROUTES } from "@/lib/constants";

/** The knowledge pages live under /rag; old links and bookmarks land there. */
export default async function KBDetailRedirectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(ROUTES.RAG_DETAIL(id));
}
