import { PageHeader } from "@/components/dashboard/page-header";
import { WorkspaceBrowser } from "@/components/sandboxes/workspace-browser";

const WORKSPACES_DESCRIPTION =
  "The files agents are keeping for you. A workspace is scratch space — it is deleted with the " +
  "conversation it belongs to and is not a place to store anything durable. Which workspaces " +
  "appear depends on who you are: your own, the ones your conversations own, and the shared " +
  "workspace of an agent you have talked to. Whoever manages sandbox connections sees the " +
  "organization's.";

/**
 * Its own page, rather than a card at the bottom of the Sandboxes screen.
 *
 * The two were together because both are about sandboxes, and that was the wrong
 * grouping: Sandboxes is an operator screen about *hosts*, gated on
 * `connections:manage`, and putting a person's own files below it meant a member
 * could not reach them at all. Files belong to whoever the agent kept them for.
 *
 * A Server Component with one client child. There is nothing to fetch here - the
 * browser reads its own data and the backend decides what it may see - so this
 * stays a heading and a sentence.
 */
export default function WorkspacesPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Workspaces" description={WORKSPACES_DESCRIPTION} />
      <WorkspaceBrowser />
    </div>
  );
}
