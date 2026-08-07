import { redirect } from "next/navigation";

import { ROUTES } from "@/lib/constants";

/** The knowledge pages live under /rag; old links and bookmarks land there. */
export default function KBRedirectPage() {
  redirect(ROUTES.RAG);
}
