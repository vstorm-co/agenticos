import { cn } from "@/lib/utils";

/** Reserve the preview's footprint; motion settles even if the renderer is slow. */
export function PreviewSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      data-preview-skeleton
      className={cn(
        "bg-background absolute inset-0 overflow-hidden rounded-lg p-4 motion-safe:animate-pulse motion-safe:[animation-iteration-count:2]",
        className,
      )}
    >
      <div className="bg-muted h-2.5 w-2/5 rounded" />
      <div className="bg-muted mt-3 h-2 w-3/5 rounded" />
      <div className="mt-5 grid h-3/5 grid-cols-3 gap-3">
        <div className="bg-muted/60 rounded-md" />
        <div className="bg-muted/60 rounded-md" />
        <div className="bg-muted/60 rounded-md" />
      </div>
    </div>
  );
}
