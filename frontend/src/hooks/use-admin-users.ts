"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useReauthenticate } from "@/hooks/use-auth";
import { apiClient } from "@/lib/api-client";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { AdminUser, AdminUserListResponse } from "@/types";

export function useAdminUsers() {
  const t = useTranslations("admin");
  const tError = useTranslations("errors");
  const router = useRouter();
  const reauthenticate = useReauthenticate();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [impersonating, setImpersonating] = useState<string | null>(null);

  const fetchUsers = useCallback(
    async ({
      skip = 0,
      limit = 50,
      search,
      sortBy,
      sortDir,
    }: {
      skip?: number;
      limit?: number;
      search?: string;
      sortBy?: string;
      sortDir?: "asc" | "desc";
    } = {}) => {
      setIsLoading(true);
      try {
        const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
        if (search) params.set("search", search);
        if (sortBy) params.set("sort_by", sortBy);
        if (sortDir) params.set("sort_dir", sortDir);
        const data = await apiClient.get<AdminUserListResponse>(`/admin/users?${params}`);
        setUsers(data.items);
        setTotal(data.total);
        setError(null);
      } catch {
        // Inline rather than a toast: a toast expires, and an empty table under
        // it then reads as a deployment with no users (#32's shape).
        setError(t("failedLoadUsers"));
      } finally {
        setIsLoading(false);
      }
    },
    [t],
  );

  const updateUser = useCallback(
    async (userId: string, patch: Partial<AdminUser>) => {
      try {
        const updated = await apiClient.patch<AdminUser>(`/admin/users/${userId}`, patch);
        setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)));
        toast.success(t("userUpdated"));
      } catch {
        toast.error(t("failedUpdateUser"));
      }
    },
    [t],
  );

  const deleteUser = useCallback(
    async (userId: string) => {
      try {
        await apiClient.delete(`/admin/users/${userId}`);
        setUsers((prev) => prev.filter((u) => u.id !== userId));
        setTotal((count) => count - 1);
        toast.success(t("userDeleted"));
      } catch (error) {
        // A refusal carries the backend's own words - deleting your own row is
        // refused with an explanation the admin should see, not the generic
        // "failed" that reads as a transient error (#941). Anything else keeps
        // the generic toast.
        toast.error(
          error instanceof ApiError ? getErrorMessage(error, tError) : t("failedDeleteUser"),
        );
      }
    },
    [t, tError],
  );

  /**
   * Start acting as a user, from here.
   *
   * The BFF swaps this browser's access cookie for the impersonation's, so the
   * answer carries no token and nothing here touches one (#1044). What follows
   * is a change of identity: the session is re-read and adopted, which empties
   * the cache and the tenant state that were the administrator's, and the
   * dashboard is opened as the account now being acted as. Answers whether it
   * happened; a refusal is a toast and `false`.
   */
  const impersonateUser = useCallback(
    async (userId: string): Promise<boolean> => {
      setImpersonating(userId);
      try {
        await apiClient.post(`/admin/users/${userId}/impersonate`);
      } catch {
        toast.error(t("failedImpersonateUser"));
        return false;
      } finally {
        setImpersonating(null);
      }
      await reauthenticate();
      const target = users.find((candidate) => candidate.id === userId);
      toast.success(t("nowActingAs", { email: target?.email ?? userId }));
      router.push(ROUTES.DASHBOARD);
      return true;
    },
    [t, users, reauthenticate, router],
  );

  return {
    users,
    total,
    isLoading,
    error,
    impersonating,
    fetchUsers,
    updateUser,
    deleteUser,
    impersonateUser,
  };
}
