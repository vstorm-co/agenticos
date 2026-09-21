import { notFound } from "next/navigation";

import { PageHeader } from "@/components/dashboard/page-header";
import { WorkflowSdkLab } from "@/components/dev/workflow-sdk/workflow-sdk-lab";

/**
 * Development-only lab for the Workflow Builder SDK evaluation (#1781). Not linked
 * from the navigation and not found in production builds, like `dev/components`.
 */
export default function WorkflowSdkLabPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <PageHeader
        title="Workflow Builder SDK lab"
        description="Evaluation of @workflowbuilder/sdk 2.3.0. Every mock is named in the decision record."
      />
      <WorkflowSdkLab />
    </div>
  );
}
