import type { LucideIcon } from "lucide-react";

import { WorkspaceAtmosphere } from "./workspace-atmosphere";
import { SectionGlyph } from "@/components/states/section-glyph";
import { cn } from "@/lib/utils";

/** One decorative language for page, gallery and table empty states. */
export function EmptyIllustration({ icon, className }: { icon: LucideIcon; className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "relative mx-auto flex h-24 w-64 max-w-full items-center justify-center",
        className,
      )}
    >
      <WorkspaceAtmosphere className="absolute inset-0 h-full w-full opacity-70" />
      <SectionGlyph icon={icon} className="relative" />
    </div>
  );
}
