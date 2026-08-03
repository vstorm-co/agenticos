import { PageHeader } from "@/components/dashboard/page-header";
import { WorkspaceExplorer } from "@/components/sandboxes/workspace-explorer";
import { getTranslations } from "next-intl/server";

/**
 * One workspace, browsable.
 *
 * Its own page rather than a card that unfolds under the table: a workspace with a
 * `skills/` directory and a couple of reports is a tree, and a flat list of every
 * path inside a table cell is not something anybody can navigate. It also means a
 * workspace has a URL, which is what makes "look at this file" a thing one person
 * can send another.
 *
 * The header says nothing about the workspace itself. Naming the agent here would
 * mean fetching the listing twice - once for a heading and once for the files - and
 * the explorer already shows whose files these are.
 */
export default async function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const t = await getTranslations("pages.workspaces");
  const { id } = await params;

  return (
    <div className="space-y-6">
      <PageHeader title={t("workspace")} description={t("whatOneAgentKeeping")} />
      <WorkspaceExplorer workspaceId={id} />
    </div>
  );
}
