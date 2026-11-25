import type { BundlePath, BundlePreview, BundleResource, ImportChoice } from "./portability-api";

const OWNED_LISTS = [
  "mcp_servers",
  "skill_bindings",
  "subagents",
  "table_bindings",
  "external_agents",
];

function container(resource: BundleResource, path: BundlePath): BundlePath {
  if (resource.kind === "workflow" && path[0] === "graph") {
    if (path[1] === "bindings") return path.slice(0, 3);
    if (path[1] === "nodes" && path[4] === "agent") return path.slice(0, 5);
  }
  if (["agent", "agent_version", "workflow"].includes(resource.kind)) {
    for (const field of OWNED_LISTS) {
      const index = path.indexOf(field);
      if (index >= 0 && typeof path[index + 1] === "number") return path.slice(0, index + 2);
    }
  }
  return path;
}

function paths(value: unknown): BundlePath[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (path): path is BundlePath =>
      Array.isArray(path) &&
      path.length > 0 &&
      path.every(
        (part: unknown) =>
          typeof part === "string" ||
          (typeof part === "number" && Number.isInteger(part) && part >= 0),
      ),
  );
}

/** A review hint only. The server verifies ownership and computes the actual omission receipt. */
export function plannedOmissions(
  preview: BundlePreview,
  choices: Record<string, ImportChoice>,
): Record<string, BundlePath[]> {
  const result: Record<string, BundlePath[]> = {};
  for (const resource of preview.bundle.resources) {
    if (choices[resource.key]?.action !== "create") continue;
    const skipped = [
      ...paths(resource.kind === "workflow" ? resource.definition?.omitted : undefined),
      ...resource.references
        .filter((ref) => choices[ref.target]?.action === "skip")
        .map((ref) => container(resource, ref.path)),
    ];
    const unique = new Map(skipped.map((path) => [JSON.stringify(path), path]));
    if (unique.size) result[resource.key] = [...unique.values()];
  }
  return result;
}

/** Changing the destination owner invalidates its dependent version and fork choices. */
export function updateImportChoice(
  preview: BundlePreview,
  previous: Record<string, ImportChoice>,
  resource: BundleResource,
  next: ImportChoice,
): Record<string, ImportChoice> {
  const updated = { ...previous, [resource.key]: next };
  const before = previous[resource.key];
  if (before?.action === next.action && before?.destination_id === next.destination_id)
    return updated;
  for (const child of preview.bundle.resources) {
    const ownerKind = child.kind === "agent_version" ? "agent" : "skill";
    if (
      resource.source_id &&
      child.source_parent_id === resource.source_id &&
      resource.kind === ownerKind &&
      previous[child.key]?.action === "reuse"
    )
      updated[child.key] = { action: "reuse", destination_id: "" };
  }
  return updated;
}

const DESTINATION_KINDS = new Set([
  "agent",
  "agent_version",
  "workflow",
  "table",
  "context",
  "skill",
  "skill_version",
  "skill_fork",
  "model_profile",
  "mcp_connection",
  "secret",
  "knowledge_base",
  "sandbox_connection",
  "local_service",
]);

export function supportsImportDestination(kind: string): boolean {
  return DESTINATION_KINDS.has(kind);
}
