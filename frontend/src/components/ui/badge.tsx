import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  // Pills, in a quiet register: a badge is metadata, and metadata set in bold
  // accent chips competes with the content it annotates.
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-foreground/8 text-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        // Status text has its own light/dark ink; action-fill colors are too
        // dark to serve as small text on a tinted surface.
        destructive: "border-transparent bg-destructive/12 text-destructive-ink",
        warning: "border-transparent bg-warning/12 text-warning-ink",
        success: "border-transparent bg-success/12 text-success-ink",
        outline: "text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  // i18n-exempt: a generic type parameter, not a text node
  extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
