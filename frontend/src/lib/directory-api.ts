/**
 * API client for an organization's directory group mappings.
 *
 * Reading them needs `members:manage`; creating or deleting one needs
 * `roles:manage` as well, and a role the caller's own strictly outranks - the
 * same rule every other write that hands a role out follows.
 */

import { apiClient } from "./api-client";
import type {
  DirectoryMapping,
  DirectoryMappingCreate,
  DirectoryMappingList,
} from "@/types/directory";

const mappings = (orgId: string) => `/orgs/${orgId}/directory-mappings`;

export async function listDirectoryMappings(orgId: string): Promise<DirectoryMappingList> {
  return apiClient.get<DirectoryMappingList>(mappings(orgId));
}

/** Refused with a 409 when that external group is already mapped here. */
export async function createDirectoryMapping(
  orgId: string,
  input: DirectoryMappingCreate,
): Promise<DirectoryMapping> {
  return apiClient.post<DirectoryMapping>(mappings(orgId), input);
}

/** The people the mapping placed leave at their next sign-in, unless taken over. */
export async function deleteDirectoryMapping(orgId: string, mappingId: string): Promise<void> {
  await apiClient.delete<void>(`${mappings(orgId)}/${mappingId}`);
}
