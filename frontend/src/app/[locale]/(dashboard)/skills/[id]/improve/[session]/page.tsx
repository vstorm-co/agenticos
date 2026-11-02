"use client";
import { use } from "react";
import { useSearchParams } from "next/navigation";
import { SkillImprovementPage } from "@/components/skill-improvement/skill-improvement-page";

export default function Page({ params }: { params: Promise<{ id: string; session: string }> }) {
  const { id, session } = use(params);
  // `?fork=` picks the line a new session improves; without it, main.
  const fork = useSearchParams().get("fork");
  return <SkillImprovementPage skillId={id} sessionId={session} forkId={fork} />;
}
