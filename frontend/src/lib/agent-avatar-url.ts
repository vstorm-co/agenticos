/** Images cannot send tenant headers; keep the selected organization in their URL. */
export function agentAvatarUrl(
  agentId: string,
  organizationId: string | null,
  version?: number,
): string {
  const query = new URLSearchParams();
  if (organizationId) query.set("organization_id", organizationId);
  if (version) query.set("v", String(version));
  const suffix = query.toString();
  return `/api/agents/${encodeURIComponent(agentId)}/avatar${suffix ? `?${suffix}` : ""}`;
}
