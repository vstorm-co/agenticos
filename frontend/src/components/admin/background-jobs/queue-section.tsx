import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { NativeDisclosure } from "@/components/ui";

export function QueueSection({
  title,
  count,
  children,
}: {
  title: string;
  count?: string;
  children: ReactNode;
}) {
  return (
    <NativeDisclosure open className="group bg-card min-w-0 rounded-xl border">
      <summary className="hover:bg-foreground/4 flex list-none items-center gap-2 px-4 py-3 focus-visible:-outline-offset-2 sm:px-5 [&::-webkit-details-marker]:hidden">
        <ChevronDown
          className="text-muted-foreground size-4 shrink-0 -rotate-90 group-open:rotate-0 rtl:group-not-open:rotate-90"
          aria-hidden
        />
        <span className="text-sm font-semibold">{title}</span>
        {count && (
          <span className="text-muted-foreground ml-auto text-xs font-normal">{count}</span>
        )}
      </summary>
      <div className="min-w-0 overflow-hidden rounded-b-xl border-t">{children}</div>
    </NativeDisclosure>
  );
}
