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
    // The height chain, in full: `main` is a flex column that scrolls, so this page
    // takes what is left of it with `flex-1` and hands the rest to the explorer.
    // Without every link the panes are as tall as their content - which for a
    // workspace holding one folder was 300 px under 600 px of nothing.
    //
    // `flex-1` and not `h-full`: the page wrapper above carries the room under a
    // page, and a child at 100% of the content box plus that padding overflows it
    // by exactly the padding - a scrollbar on every page that would otherwise
    // have none.
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader title={t("workspace")} description={t("whatOneAgentKeeping")} />
      <div data-tour="workspace-files" className="flex min-h-0 flex-1 flex-col">
        <WorkspaceExplorer workspaceId={id} />
      </div>
    </div>
  );
}
