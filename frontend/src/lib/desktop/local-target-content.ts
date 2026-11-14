import { sameJson } from "@/lib/canonical-json";
import type { LocalTarget } from "./commands";

/** Compare the normalized target, including its existing consent receipts. */
export function sameLocalTarget(left: LocalTarget | null, right: LocalTarget | null): boolean {
  const content = (target: LocalTarget | null) =>
    target === null
      ? null
      : {
          folder: target.folder,
          device_id: target.device_id ?? null,
          mode: target.mode,
          routine_grant: target.routine_grant ?? null,
          computer_grant: target.computer_grant ?? null,
          computer_grant_agent: target.computer_grant_agent ?? null,
          operations: target.operations ?? null,
          model_service: target.model_service ?? null,
          mcp_services: target.mcp_services ?? [],
          computer: target.computer ?? false,
          browser: target.browser ?? false,
          coding_agent: target.coding_agent ?? null,
          coding_model: target.coding_model ?? null,
          coding_effort: target.coding_effort ?? null,
          skills: target.skills ?? [],
        };
  return sameJson(content(left), content(right));
}
