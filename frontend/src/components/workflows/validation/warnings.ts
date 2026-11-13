import { ERROR_PORT } from "@/lib/workflows/ports";
import type { NodeCatalog, WorkflowGraph } from "@/lib/workflows/types";

import type { ValidationProblem } from "./index";
import { resolveDefinitions } from "./topology";
import type { ValidationTranslator } from "./types";

const APPROVAL = "human.approval";

/**
 * What is worth a second look but may be meant: never a reason to refuse a test run
 * or a publish, so it is kept apart from {@link validateGraph}, whose every problem
 * blocks both - and the server, which has no such level, is not mirrored here.
 *
 * - An approval names each outcome nothing follows: a builder who added it after a
 *   step usually wired one outcome and forgot the other, and the run then simply
 *   ends there after a person decided.
 * - Any other step that decides between outputs is flagged only when none of them
 *   leads anywhere - an `if` whose false side ends the run is a common, sound shape.
 */
export function graphWarnings(
  graph: WorkflowGraph,
  catalog: NodeCatalog,
  t: ValidationTranslator,
): ValidationProblem[] {
  const definitions = resolveDefinitions(graph, catalog);
  const wired = new Set(
    graph.edges.map((edge) => `${edge.source_node_id}\u0000${edge.source_port}`),
  );
  const warnings: ValidationProblem[] = [];
  for (const node of graph.nodes) {
    const definition = definitions.get(node.id);
    if (!definition?.exclusive_branches || node.disabled === true) continue;
    const outputs = definition.ports.filter(
      (port) => port.kind === "output" && port.id !== ERROR_PORT,
    );
    const open = outputs.filter((port) => !wired.has(`${node.id}\u0000${port.id}`));
    const warn = (code: string, message: string) =>
      warnings.push({ nodeId: node.id, edgeId: null, field: null, code, message });
    if (definition.id === APPROVAL) {
      for (const port of open) {
        warn(
          "approval-outcome-unwired",
          t("validationApprovalOutcomeUnwired", { outcome: port.label }),
        );
      }
    } else if (outputs.length > 0 && open.length === outputs.length) {
      warn("branch-outputs-unwired", t("validationBranchOutputsUnwired"));
    }
  }
  return warnings;
}
