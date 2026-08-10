import { PageHeader } from "@/components/dashboard/page-header";
import { WorkspaceBrowser } from "@/components/sandboxes/workspace-browser";
import { useTranslations } from "next-intl";

const WORKSPACES_DESCRIPTION = "pageDescription";

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
  const t = useTranslations("pages.workspaces");
  return (
    <div className="space-y-6">
      <PageHeader title={t("workspaces")} description={t(WORKSPACES_DESCRIPTION)} />
      <div data-tour="workspaces-browser">
        <WorkspaceBrowser />
      </div>
    </div>
  );
}
