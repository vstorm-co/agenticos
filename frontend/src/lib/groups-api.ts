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
  GroupResourceList,
  GroupShareRequest,
  GroupSpendList,
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

/** Make a member the group's lead, or not - administrators only. */
export async function setGroupLead(
  orgId: string,
  groupId: string,
  userId: string,
  isLead: boolean,
): Promise<GroupMember> {
  return apiClient.patch<GroupMember>(`${members(orgId, groupId)}/${userId}`, { is_lead: isLead });
}

/** What the caller could share with a group: what they may edit, not shared with it yet. */
export async function listShareableWithGroup(
  orgId: string,
  groupId: string,
): Promise<GroupResourceList> {
  return apiClient.get<GroupResourceList>(`${group(orgId, groupId)}/shareable`);
}

/** Share several resources with a group at once. */
export async function shareWithGroup(
  orgId: string,
  groupId: string,
  request: GroupShareRequest,
): Promise<void> {
  await apiClient.post<void>(`${group(orgId, groupId)}/shares`, request);
}

/** Every department's month to date against its cap. Needs `runs:view`. */
export async function getGroupSpend(orgId: string): Promise<GroupSpendList> {
  return apiClient.get<GroupSpendList>(`${groups(orgId)}/spend`);
}

/** One department's month as CSV - `runs:view`, or the department's lead. */
export async function downloadGroupSpend(orgId: string, groupId: string): Promise<Blob> {
  return (await apiClient.raw(`${group(orgId, groupId)}/spend.csv`)).blob();
}

/** What has been shared with a group, narrowed to what the caller may see. */
export async function listGroupResources(
  orgId: string,
  groupId: string,
): Promise<GroupResourceList> {
  return apiClient.get<GroupResourceList>(`${group(orgId, groupId)}/resources`);
}
