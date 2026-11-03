"use client";
import { use } from "react";
import { useSearchParams } from "next/navigation";
import { SkillImprovementPage } from "@/components/skill-improvement/skill-improvement-page";

export default function Page({ params }: { params: Promise<{ id: string; session: string }> }) {
  const { id, session } = use(params);
  // `?fork=` picks the line a new session improves; `?from_run=` hands an agent's
  // session over, whose problems the new one starts from; `?merge=` merges the fork
  // with main instead, catching it up or moving it to main.
  const search = useSearchParams();
  const merge = search.get("merge");
  return (
    <SkillImprovementPage
      skillId={id}
      sessionId={session}
      forkId={search.get("fork")}
      fromRun={search.get("from_run")}
      merge={merge === "catch_up" || merge === "to_main" ? merge : null}
    />
  );
}
