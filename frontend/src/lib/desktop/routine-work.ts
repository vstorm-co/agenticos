/** Explicit native grants are scoped to one routine, owner, organization and device. */
import { z } from "zod";

import type { LocalTarget } from "@/lib/desktop/commands";
import { invokeShell, ShellError } from "@/lib/desktop/shell";

export const deviceIdentitySchema = z.object({
  origin: z.url(),
  user_id: z.uuid(),
  device_id: z.uuid(),
});
export type DeviceIdentity = z.infer<typeof deviceIdentitySchema>;
export const localOperationsSchema = z
  .object({ read: z.literal(true), write: z.boolean(), execute: z.boolean() })
  .strict()
  .refine((operations) => !operations.execute || operations.write);
export type LocalOperations = z.infer<typeof localOperationsSchema>;
const grantSchema = z.object({
  id: z.uuid(),
  identity: deviceIdentitySchema,
  organization_id: z.uuid(),
  routine_id: z.uuid(),
  name: z.string(),
  root: z.string().min(1),
  operations: localOperationsSchema,
});
export type RoutineGrant = z.infer<typeof grantSchema>;
export interface RoutineGrantRequest {
  organization_id: string;
  routine_id: string;
  user_id: string;
  device_id: string;
  name: string;
  root: string;
  operations: LocalOperations;
}

function decode<T>(schema: z.ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);
  if (!result.success) throw new ShellError("malformed", "routine permission");
  return result.data;
}

export async function chooseRoutineFolder(): Promise<string | null> {
  return decode(z.string().min(1).nullable(), await invokeShell("routine_choose_folder"));
}

export async function allowRoutine(request: RoutineGrantRequest): Promise<LocalTarget | null> {
  localOperationsSchema.parse(request.operations);
  const grant = decode(grantSchema.nullable(), await invokeShell("routine_allow", { request }));
  if (grant === null) return null;
  if (
    grant.organization_id !== request.organization_id ||
    grant.routine_id !== request.routine_id ||
    grant.identity.user_id !== request.user_id ||
    grant.identity.device_id !== request.device_id ||
    grant.root !== request.root ||
    grant.operations.write !== request.operations.write ||
    grant.operations.execute !== request.operations.execute
  ) {
    throw new ShellError("malformed", "routine permission binding changed");
  }
  return {
    device_id: grant.identity.device_id,
    folder: grant.root,
    mode: grant.operations.write ? "workspace_write" : "read_only",
    routine_grant: grant.id,
    operations: grant.operations,
  };
}

export async function listRoutineGrants(organizationId: string, userId: string) {
  const grants = decode(
    z.array(grantSchema),
    await invokeShell("routine_grants", { organizationId, userId }),
  );
  if (
    grants.some(
      (grant) => grant.organization_id !== organizationId || grant.identity.user_id !== userId,
    )
  )
    throw new ShellError("malformed", "routine permission owner changed");
  return grants;
}

export async function revokeRoutineGrant(id: string, organizationId: string, userId: string) {
  await invokeShell("routine_revoke", { id, organizationId, userId });
}
