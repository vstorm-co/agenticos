import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";

export type SkillPackageFormat = "directory" | "zip";
export interface SkillPackagePreview {
  name: string;
  description: string;
  content: string;
  category: string | null;
  manifest_metadata: Record<string, unknown>;
  fingerprint: string;
  files: { name: string; size_bytes: number; sha256: string; encoding: "utf8" | "base64" }[];
  total_bytes: number;
  max_file_bytes: number;
  max_package_bytes: number;
  max_files: number;
  execution: "none";
}
export interface SkillPackageApplied {
  skill_id: string;
  version_id: string;
  name: string;
  files: number;
  fingerprint: string;
}
function packageForm(files: readonly File[], format: SkillPackageFormat): FormData {
  const form = new FormData();
  form.append("format", format);
  for (const file of files) form.append("files", file, file.webkitRelativePath || file.name);
  return form;
}
export function previewSkillPackage(files: readonly File[], format: SkillPackageFormat) {
  return apiClient.upload<SkillPackagePreview>(
    "/skills/import/preview",
    packageForm(files, format),
  );
}
export function applySkillPackage(
  files: readonly File[],
  format: SkillPackageFormat,
  fingerprint: string,
) {
  const form = packageForm(files, format);
  form.append("fingerprint", fingerprint);
  return apiClient.upload<SkillPackageApplied>("/skills/import", form);
}
export async function downloadSkillFile(
  skillId: string,
  name: string,
  source: { resourceId: string } | { versionId: string },
): Promise<void> {
  const endpoint =
    "resourceId" in source
      ? `/skills/${encodeURIComponent(skillId)}/resources/${encodeURIComponent(source.resourceId)}/download`
      : `/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(source.versionId)}/download/${name.split("/").map(encodeURIComponent).join("/")}`;
  const response = await apiClient.raw(endpoint);
  saveBlob(await response.blob(), name.split("/").at(-1) || name);
}
