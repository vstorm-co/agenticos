/**
 * Explicit native grants: for one routine on one session, or for every routine of
 * the person in an organization (`routine_id: null`), on this computer.
 */
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
  routine_id: z.uuid().nullable(),
  name: z.string(),
  root: z.string().min(1),
  operations: localOperationsSchema,
});
export type RoutineGrant = z.infer<typeof grantSchema>;
export interface RoutineGrantRequest {
  organization_id: string;
  /** One routine, or null for every routine of this person. */
  routine_id: string | null;
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
  return targetFor(grant, grant.identity.device_id, grant.root, grant.operations);
}

function targetFor(
  grant: RoutineGrant,
  deviceId: string,
  folder: string,
  operations: LocalOperations,
): LocalTarget {
  return {
    device_id: deviceId,
    folder,
    mode: operations.write ? "workspace_write" : "read_only",
    routine_grant: grant.id,
    operations,
  };
}

function within(folder: string, root: string): boolean {
  const parent = root.replace(/[\\/]+$/, "");
  return (
    folder === parent ||
    parent === "" ||
    folder.startsWith(`${parent}/`) ||
    folder.startsWith(`${parent}\\`)
  );
}

/**
 * A routine's folder under the person's grant for every routine, on the session
 * signed in now - no dialog. Null when no such grant covers the folder and the
 * operations asked for.
 */
export function coveredByAllRoutines(
  grants: readonly RoutineGrant[],
  deviceId: string,
  folder: string,
  operations: LocalOperations,
): LocalTarget | null {
  const grant = grants.find(
    (candidate) =>
      candidate.routine_id === null &&
      within(folder, candidate.root) &&
      (!operations.write || candidate.operations.write) &&
      (!operations.execute || candidate.operations.execute),
  );
  return grant ? targetFor(grant, deviceId, folder, operations) : null;
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
