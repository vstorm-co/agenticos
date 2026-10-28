/**
 * API client for projects: the projects themselves and the files they hold.
 *
 * A project's files are read through the project rather than through the
 * Documents screen's workspace routes, because whoever the project is shared
 * with may read them - and the workspace routes authorise per agent workspace.
 */

import { apiClient } from "./api-client";
import type { FileText } from "./file-access";
import { postWithProgress } from "./upload-with-progress";
import type { WorkspaceFiles } from "./sandbox-workspaces-api";
import type { Conversation, ProjectChat } from "@/types/conversation";
import type {
  Project,
  ProjectCreate,
  ProjectList,
  ProjectUpdate,
  ProjectWorkspaceMove,
} from "@/types/projects";

const ROOT = "/projects";

export interface ProjectQuery {
  search: string;
  skip: number;
  limit: number;
}

export async function listProjects({ search, skip, limit }: ProjectQuery): Promise<ProjectList> {
  const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
  if (search) params.set("q", search);
  return apiClient.get<ProjectList>(`${ROOT}?${params}`);
}

export async function getProject(id: string): Promise<Project> {
  return apiClient.get<Project>(`${ROOT}/${id}`);
}

export async function createProject(input: ProjectCreate): Promise<Project> {
  return apiClient.post<Project>(ROOT, input);
}

export async function updateProject(id: string, changes: ProjectUpdate): Promise<Project> {
  return apiClient.patch<Project>(`${ROOT}/${id}`, changes);
}

export async function deleteProject(id: string): Promise<void> {
  await apiClient.delete<void>(`${ROOT}/${id}`);
}

export interface ProjectChatList {
  items: ProjectChat[];
  total: number;
}

/** Every chat in the project, whoever started it, with who saw it and who works in it. */
export async function listProjectChats(
  id: string,
  skip: number,
  limit: number,
): Promise<ProjectChatList> {
  return apiClient.get<ProjectChatList>(`${ROOT}/${id}/chats?skip=${skip}&limit=${limit}`);
}

/** The project a conversation was started in, or null for one outside any. */
export async function projectOfConversation(conversationId: string): Promise<string | null> {
  const conversation = await apiClient.get<Pick<Conversation, "project_id">>(
    `/conversations/${conversationId}/metadata`,
  );
  return conversation.project_id ?? null;
}

export async function listProjectFiles(id: string): Promise<WorkspaceFiles> {
  return apiClient.get<WorkspaceFiles>(`${ROOT}/${id}/files`);
}

export async function readProjectBytes(
  id: string,
  path: string,
  { download = false }: { download?: boolean } = {},
): Promise<Blob> {
  const response = await apiClient.raw(
    `${ROOT}/${id}/files/raw?path=${encodeURIComponent(path)}${download ? "&download=true" : ""}`,
  );
  return response.blob();
}

/**
 * One file's text, decoded from its bytes.
 *
 * A project has no text route of its own: its files are ones a person put there,
 * held under the upload limit, so the bytes are the whole answer.
 */
export async function readProjectText(id: string, path: string): Promise<FileText> {
  return { content: await (await readProjectBytes(id, path)).text(), truncated: false };
}

/**
 * Add one file, at `path` inside the project - a folder upload's relative path -
 * reporting how much of it has been sent, as a knowledge-base upload does.
 */
export async function uploadProjectFile(
  id: string,
  file: File,
  path: string,
  progress: Parameters<typeof postWithProgress>[2],
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  form.append("path", path);
  await postWithProgress(`${ROOT}/${id}/files`, form, progress);
}

export async function createProjectFolder(id: string, path: string): Promise<{ path: string }> {
  return apiClient.post<{ path: string }>(`${ROOT}/${id}/folders`, { path });
}

/** Remove a file, or a folder with everything in it. */
export async function removeProjectPath(id: string, path: string): Promise<void> {
  await apiClient.delete<void>(`${ROOT}/${id}/files?path=${encodeURIComponent(path)}`);
}

export interface EditableProjectFile {
  content: string;
  revision: string;
}

export function moveProjectPath(
  id: string,
  source: string,
  destination: string,
): Promise<{ path: string }> {
  return apiClient.post(`${ROOT}/${id}/files/move`, { source, destination });
}

export function readEditableProjectFile(id: string, path: string): Promise<EditableProjectFile> {
  return apiClient.get(`${ROOT}/${id}/files/text?${new URLSearchParams({ path })}`);
}

export function saveProjectFile(
  id: string,
  path: string,
  file: EditableProjectFile,
): Promise<EditableProjectFile> {
  return apiClient.put(`${ROOT}/${id}/files/text?${new URLSearchParams({ path })}`, file);
}

/** Activate a new sandbox only after the worker has copied and verified its files. */
export async function moveProjectWorkspace(
  id: string,
  target: string,
): Promise<ProjectWorkspaceMove> {
  return apiClient.post<ProjectWorkspaceMove>(`${ROOT}/${id}/workspace-move`, {
    backend: target === "state" ? "state" : "service",
    sandbox_connection_id: target === "state" ? null : target,
  });
}
