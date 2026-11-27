import type { QueryClient } from "@tanstack/react-query";
import type { ImportReceipt } from "./portability-api";
import { qk } from "./query-keys";

/** Refresh catalogs after the import committed, not while its worker is merely queued. */
export async function invalidateImportedResources(
  client: QueryClient,
  receipt: ImportReceipt,
): Promise<void> {
  const catalogs: Record<string, readonly (readonly unknown[])[]> = {
    agent: [qk.agents.all()],
    workflow: [qk.workflows.all()],
    context: [qk.context.all()],
    skill: [qk.skills.all()],
    skill_version: [qk.skills.all()],
    skill_fork: [qk.skills.all()],
    model_profile: [qk.providers.modelProfiles()],
    knowledge_base: [qk.kb.all()],
    mcp_connection: [qk.mcpConnections.all(), qk.mcpServers.lists(), qk.mcpServers.entries()],
  };
  const keys = Object.keys({ ...receipt.roots, ...receipt.created }).flatMap(
    (key) => catalogs[key.substring(0, key.indexOf("/"))] ?? [],
  );
  const unique = new Map(keys.map((key) => [JSON.stringify(key), key]));
  await Promise.all([...unique.values()].map((queryKey) => client.invalidateQueries({ queryKey })));
}
