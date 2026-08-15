"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import type { AdminUser, AdminUserListResponse } from "@/types";

interface ImpersonateResponse {
  access_token: string;
  token_type: string;
  impersonated_user_id: string;
  impersonated_by: string;
  expires_in: number;
}

export function useAdminUsers() {
  const t = useTranslations("admin");
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
      } catch {
        toast.error(t("failedDeleteUser"));
      }
    },
    [t],
  );

  const impersonateUser = useCallback(
    async (userId: string) => {
      setImpersonating(userId);
      try {
        const { access_token } = await apiClient.post<ImpersonateResponse>(
          `/admin/users/${userId}/impersonate`,
        );
        return access_token;
      } catch {
        toast.error(t("failedImpersonateUser"));
        return null;
      } finally {
        setImpersonating(null);
      }
    },
    [t],
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
