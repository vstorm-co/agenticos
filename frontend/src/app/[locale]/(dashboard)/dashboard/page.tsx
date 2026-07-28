import { Construction } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState } from "@/components/states";
import { ROUTES } from "@/lib/constants";

export default function DashboardPage() {
  return (
    <div className="pb-8">
      <PageHeader
        title="Dashboard"
        description="This page is being rebuilt — the widgets that used to live here have been removed."
      />
      <EmptyState
        icon={Construction}
        title="Under construction"
        description="We're reworking what the dashboard should show. Everything else in the workspace works as usual."
        cta={{ label: "Go to chat", href: ROUTES.CHAT }}
        secondaryCta={{ label: "Agents", href: ROUTES.AGENTS }}
      />
    </div>
  );
}
