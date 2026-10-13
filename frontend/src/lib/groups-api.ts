/**
 * API client for an organization's groups and who is in them.
 *
 * Every path names the organization, because the pages calling it name one in
 * their URL and *are* that organization - the distinction #1032 was about.
 */

import { apiClient } from "./api-client";
import type {
  Group,
  GroupCreate,
  GroupList,
  GroupMember,
  GroupMemberList,
  GroupUpdate,
} from "@/types/groups";

const groups = (orgId: string) => `/orgs/${orgId}/groups`;
const group = (orgId: string, groupId: string) => `${groups(orgId)}/${groupId}`;
const members = (orgId: string, groupId: string) => `${group(orgId, groupId)}/members`;

export async function listGroups(orgId: string): Promise<GroupList> {
  return apiClient.get<GroupList>(groups(orgId));
}

export async function createGroup(orgId: string, input: GroupCreate): Promise<Group> {
  return apiClient.post<Group>(groups(orgId), input);
}

export async function updateGroup(
  orgId: string,
  groupId: string,
  input: GroupUpdate,
): Promise<Group> {
  return apiClient.patch<Group>(group(orgId, groupId), input);
}

/** Also deletes every grant made to the group and every directory mapping naming it. */
export async function deleteGroup(orgId: string, groupId: string): Promise<void> {
  await apiClient.delete<void>(group(orgId, groupId));
}

export async function listGroupMembers(orgId: string, groupId: string): Promise<GroupMemberList> {
  return apiClient.get<GroupMemberList>(members(orgId, groupId));
}

/** Refused with a 400 for somebody who is not a member of the organization. */
export async function addGroupMember(
  orgId: string,
  groupId: string,
  userId: string,
): Promise<GroupMember> {
  return apiClient.post<GroupMember>(members(orgId, groupId), { user_id: userId });
}

export async function removeGroupMember(
  orgId: string,
  groupId: string,
  userId: string,
): Promise<void> {
  await apiClient.delete<void>(`${members(orgId, groupId)}/${userId}`);
}
