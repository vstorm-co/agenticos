import { apiClient } from "@/lib/api-client";
import { userAppearanceSchema, type UserAppearance } from "@/lib/user-appearance";

const PATH = "/users/me/appearance";

export async function getUserAppearance(signal?: AbortSignal): Promise<UserAppearance> {
  return userAppearanceSchema.parse(await apiClient.get<unknown>(PATH, { signal }));
}
export async function saveUserAppearance(
  changes: Partial<UserAppearance>,
): Promise<UserAppearance> {
  return userAppearanceSchema.parse(await apiClient.patch<unknown>(PATH, changes));
}
export async function resetUserAppearance(): Promise<UserAppearance> {
  return userAppearanceSchema.parse(await apiClient.delete<unknown>(PATH));
}
