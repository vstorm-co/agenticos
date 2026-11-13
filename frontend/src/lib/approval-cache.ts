import type { QueryClient } from "@tanstack/react-query";
import type { Outcome } from "@/lib/outcomes-api";
import { qk } from "@/lib/query-keys";

/** Patch only this acknowledged run; an in-flight read must not revive its notice. */
export async function clearApprovalNotice(
  client: QueryClient,
  conversationId: string | null,
  runId: string,
): Promise<void> {
  if (conversationId === null) return;
  const key = qk.outcomes.conversation(conversationId);
  await client.cancelQueries({ queryKey: key });
  client.setQueryData<Outcome[]>(key, (items) =>
    items?.filter((item) => item.kind !== "approval_requested" || item.source_run_id !== runId),
  );
}
