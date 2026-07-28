"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type { LibrarySkillList, Skill, SkillList, SkillResource } from "@/types/providers";

export interface NewSkill {
  name: string;
  description: string;
  content: string;
  /** A grouping label for the listing; omitted means uncategorized. */
  category?: string | null;
}

/** How the server may order a listing. */
export type SkillSort = "name" | "updated";

/** Which slice of the organization's skills to ask for. */
export interface SkillQuery {
  /** Matched against name and description, by the database. */
  search?: string;
  /** An exact category to filter to; undefined means every shelf. */
  category?: string;
  sort?: SkillSort;
  skip?: number;
  limit?: number;
}

/**
 * An organization's reusable know-how.
 *
 * The list returns names and descriptions only - the bodies can be long, and
 * the picker never needs them.
 *
 * Searching and paging happen on the server: an organization's skills grow
 * without bound, so the client cannot assume it holds them all. `total` is the
 * count before paging, which is what a pager needs and what tells a caller
 * whether the slice it got is the whole set.
 */
export function useSkills({
  search = "",
  category,
  sort = "name",
  skip = 0,
  limit = PAGE_SIZE,
}: SkillQuery = {}) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.skills.list({ search, category: category ?? "", sort, skip, limit }),
    queryFn: () =>
      apiClient.get<SkillList>("/skills", {
        params: {
          ...(search ? { q: search } : {}),
          ...(category ? { category } : {}),
          sort,
          skip: String(skip),
          limit: String(limit),
        },
      }),
    placeholderData: (previous) => previous,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.skills.all() }),
    [queryClient],
  );

  // No `onError` here, unlike its neighbours: every way this fails - the name
  // is taken, the description is too long - is something the reader can fix in
  // the dialog still on screen, so the dialog decides where to say it. See
  // `CreateSkillDialog`.
  const create = useMutation({
    mutationFn: (skill: NewSkill) => apiClient.post<Skill>("/skills", skill),
    onSuccess: async (skill) => {
      await invalidate();
      toast.success(`Created ${skill.name}`);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, ...changes }: { id: string } & Partial<NewSkill>) =>
      apiClient.patch<Skill>(`/skills/${id}`, changes),
    onSuccess: async () => {
      await invalidate();
      // Skills are bound by reference, so an edit reaches every agent at once.
      toast.success("Saved. Every agent using this skill is now current.");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/skills/${id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success("Skill deleted");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return {
    skills: data?.items ?? [],
    total: data?.total ?? 0,
    categories: data?.categories ?? [],
    isLoading,
    create,
    update,
    remove,
  };
}

/** What the editor may change on a skill that already exists. */
export interface SkillEdit {
  description: string;
  content: string;
  enabled: boolean;
  /** Null clears the category; the listing then shows the skill unshelved. */
  category: string | null;
}

/**
 * One skill, body included.
 *
 * Separate from the list because the list omits `content` - the picker never
 * needs a body, and the editor cannot work without one. The editable set is
 * narrower than `NewSkill` in one direction and wider in the other: the API
 * refuses to rename a skill, because the name is the handle agents and the
 * model both use, and `enabled` only means something once it exists.
 */
export function useSkill(skillId: string | null) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.skills.detail(skillId ?? ""),
    queryFn: () => apiClient.get<Skill>(`/skills/${skillId}`),
    enabled: skillId !== null,
  });

  const save = useMutation({
    mutationFn: (edit: SkillEdit) => apiClient.patch<Skill>(`/skills/${skillId}`, edit),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      // Agents bind to the skill, not to a version of it, so this is already live.
      toast.success("Saved. Every agent using this skill is now current.");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  /**
   * Attach a file to the skill.
   *
   * The body says how the work is done; a file is the detail that would bury
   * the instructions if it were inlined, and that the model loads only when it
   * decides it needs it. Adding one bumps the skill's version, so every bound
   * agent is executing against the new set from its next run.
   */
  const addResource = useMutation({
    mutationFn: (resource: NewSkillResource) =>
      apiClient.post<SkillResource>(`/skills/${skillId}/resources`, resource),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      toast.success("File added");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const saveResource = useMutation({
    mutationFn: ({ id, ...edit }: { id: string; description?: string | null; content?: string }) =>
      apiClient.patch<SkillResource>(`/skills/${skillId}/resources/${id}`, edit),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      toast.success("File saved");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const removeResource = useMutation({
    mutationFn: (resourceId: string) =>
      apiClient.delete<void>(`/skills/${skillId}/resources/${resourceId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      toast.success("File removed");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  /**
   * Write several files at once - a dropped folder, or a handful of files.
   *
   * Each keeps the relative path the browser sent, which is exactly the name a
   * resource takes, so a folder arrives as a folder with nothing to
   * reconstruct. A path that already exists is replaced: somebody dropping a
   * corrected folder in means the corrected version.
   */
  const uploadResources = useMutation({
    mutationFn: (files: File[]) =>
      apiClient.uploadMany<{ items: SkillResource[] }>(
        `/skills/${skillId}/resources/upload`,
        files,
        // `webkitRelativePath` is the folder-picker's path and the plain name is
        // what a multi-file pick sends; the server takes either as the name.
        (file) => file.webkitRelativePath || file.name,
      ),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      const count = result.items.length;
      toast.success(`${count} file${count === 1 ? "" : "s"} uploaded`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return {
    skill: data,
    isLoading,
    save,
    addResource,
    saveResource,
    removeResource,
    uploadResources,
  };
}

/** One file with its body - the listing on the skill carries only the names. */
export function useSkillResource(skillId: string | null, resourceId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.skills.resource(skillId ?? "", resourceId ?? ""),
    queryFn: () => apiClient.get<SkillResource>(`/skills/${skillId}/resources/${resourceId}`),
    enabled: skillId !== null && resourceId !== null,
  });
  return { resource: data, isLoading };
}

/**
 * The skills this deployment ships with.
 *
 * Bundled in the repository rather than fetched from a registry, so the list
 * changes on redeploy and not between requests - hence the indefinite cache.
 * Installing copies: from that moment it is an ordinary skill the organization
 * owns and edits.
 */
export function useSkillLibrary() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.skills.library(),
    queryFn: () => apiClient.get<LibrarySkillList>("/skills/library"),
  });

  const install = useMutation({
    mutationFn: (key: string) => apiClient.post<Skill>(`/skills/library/${key}/install`, {}),
    onSuccess: async (skill) => {
      await queryClient.invalidateQueries({ queryKey: qk.skills.all() });
      toast.success(`${skill.name} installed - it is yours to edit now`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return { library: data?.items ?? [], isLoading, install };
}

export interface NewSkillResource {
  name: string;
  description?: string | null;
  content: string;
}
