import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("bg-muted max-w-full animate-pulse rounded-md", className)} {...props} />
  );
}

export { Skeleton };
