import { notFound } from "next/navigation";

import { VisualWorkspacePreview } from "@/components/dev/visual-workspace-preview";

/** A development gallery using the configured visual renderer and chat workspace. */
export default function VisualsPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <VisualWorkspacePreview />;
}
