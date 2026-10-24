"use client";
import { use } from "react";
import { ImprovementPage } from "@/components/improvement/improvement-page";
export default function Page({ params }: { params: Promise<{ id: string; session: string }> }) {
  const { id, session } = use(params);
  return <ImprovementPage agentId={id} sessionId={session} />;
}
