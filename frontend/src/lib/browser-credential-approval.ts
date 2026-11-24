import type { ToolApproval } from "@/types/runs";
import { isBrowserCredentialId } from "./browser-credential-review";

export interface BrowserCredentialSelection {
  runId: string;
  planId: string;
  continuationId?: string;
}
export const isBrowserCredentialPreparation = (tool: string | null | undefined) =>
  tool === "browser_fill_credential";
export function browserCredentialApproval(
  approval: ToolApproval,
):
  { kind: "ordinary" } | { kind: "unavailable" } | ({ kind: "plan" } & BrowserCredentialSelection) {
  const tool = approval.capability_tool_id ?? approval.tool_id;
  if (tool === "browser_continue_credential_session") {
    const args = approval.tool_args;
    if (
      !args ||
      Array.isArray(args) ||
      Object.keys(args).length !== 2 ||
      !Object.hasOwn(args, "continuation_id") ||
      !Object.hasOwn(args, "source_submission_id") ||
      approval.content_hidden !== false ||
      approval.always_asks !== true ||
      args.continuation_id !== approval.id ||
      !isBrowserCredentialId(approval.id) ||
      !isBrowserCredentialId(approval.run_id) ||
      !isBrowserCredentialId(args.source_submission_id)
    )
      return { kind: "unavailable" };
    return {
      kind: "plan",
      runId: approval.run_id,
      planId: args.source_submission_id,
      continuationId: approval.id,
    };
  }
  if (tool !== "browser_fill_credential" && tool !== "browser_submit_credential_form")
    return { kind: "ordinary" };
  // An operator-gated invocation can prepare a request, but is not plan consent.
  const args = approval.tool_args ?? {};
  if (!Object.hasOwn(args, "plan_id")) return { kind: "ordinary" };
  if (
    approval.content_hidden ||
    args.plan_id !== approval.id ||
    !isBrowserCredentialId(approval.id) ||
    !isBrowserCredentialId(approval.run_id)
  ) {
    return { kind: "unavailable" };
  }
  return { kind: "plan", runId: approval.run_id, planId: approval.id };
}
