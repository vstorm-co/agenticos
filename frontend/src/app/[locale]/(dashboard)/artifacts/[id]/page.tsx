import { ArtifactDetail } from "@/components/artifacts/artifact-detail";

/**
 * One artifact: the page itself, its versions, and who may open it.
 *
 * `?version=` is how a conversation links to the version its run published, so
 * the chat keeps showing what was written then after the agent republishes.
 */
export default async function ArtifactPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ version?: string }>;
}) {
  const { id } = await params;
  const { version } = await searchParams;
  return <ArtifactDetail artifactId={id} initialVersionId={version ?? null} />;
}
