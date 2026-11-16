"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LoadingState } from "@/components/states";

/** Preserve old start links while opening the form over the Agent Builder. */
export function ImprovementStartRedirect({ agentId }: { agentId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const query = new URLSearchParams({
    improve:
      [
        params.get("baseline") === "1" ? "baseline" : "",
        params.get("resume") === "1" ? "resume" : "",
      ]
        .filter(Boolean)
        .join("-") || "new",
  });
  const dataset = params.get("dataset");
  if (dataset) query.set("improveDataset", dataset);
  const target = `/agents/${agentId}?${query}`;
  useEffect(() => {
    router.replace(target);
  }, [router, target]);
  return <LoadingState variant="pending" />;
}
