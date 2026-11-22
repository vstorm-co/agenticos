"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_BROAD, DIALOG_CANVAS, DIALOG_COLUMN, DIALOG_FILL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";

/** Category selection stays compact; a selected library gets a bounded reading canvas. */
export function TemplateLibraryDialog({
  open,
  onOpenChange,
  title,
  description,
  detail,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  detail: boolean;
  children: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(detail ? [DIALOG_FILL, DIALOG_CANVAS] : [DIALOG_COLUMN, DIALOG_BROAD])}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

export function TemplateCategoryButton({
  icon: Icon,
  title,
  count,
  description,
  onClick,
}: {
  icon: LucideIcon;
  title: string;
  count: string;
  description?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group hover:border-primary hover:bg-accent focus-visible:ring-ring grid grid-cols-[2rem_minmax(0,1fr)] items-center gap-x-3 gap-y-1 rounded-lg border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none sm:flex sm:flex-col sm:gap-2 sm:p-5 sm:text-center"
    >
      <Icon
        className={cn(
          "text-muted-foreground group-hover:text-primary size-7 transition-colors sm:size-8",
          description ? "row-span-4" : "row-span-3",
        )}
        aria-hidden
      />
      <span className="font-medium">{title}</span>
      <span className="text-muted-foreground text-sm">{count}</span>
      {description && <span className="text-muted-foreground text-sm">{description}</span>}
    </button>
  );
}

export function TemplateLibraryItem({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 rounded-xl border p-4 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:gap-x-4">
      {children}
    </div>
  );
}
