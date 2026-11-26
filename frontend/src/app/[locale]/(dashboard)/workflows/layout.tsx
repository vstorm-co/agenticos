import type { ReactNode } from "react";
import "@/components/workflows/workflow-fields.css";

export default function WorkflowsLayout({ children }: { children: ReactNode }) {
  return (
    <div data-workflow-fields className="flex min-h-0 flex-1 flex-col">
      {children}
    </div>
  );
}
