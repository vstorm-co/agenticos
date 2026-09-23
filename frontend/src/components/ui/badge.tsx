import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  // Pills, in a quiet register: a badge is metadata, and metadata set in bold
  // accent chips competes with the content it annotates.
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        // Tinted, not filled - and the text is `foreground`, not the tone.
        //
        // This was a solid red pill with white text, which contradicted the
        // rule two lines above it: metadata set in a bold accent chip competes
        // with the content it annotates, and five of these on a table of
        // connections read as five alarms.
        //
        // The text colour is the part worth measuring. Tone-on-tone - red text
        // on a red tint - is what it looks like it should be and is the one
        // thing that does not work: `text-destructive` on `bg-destructive/15`
        // measures **2.70:1** on the dark card, under every floor there is.
        // `text-foreground` on the same tint measures 12.18:1 dark and 16.45:1
        // light. So the tint and the border carry the hue and the text stays
        // legible, which is also the shape `announcement-banner` and
        // `deployment-gate` already use.
        destructive: "border-destructive/35 bg-destructive/10 text-foreground",
        warning: "border-warning/35 bg-warning/10 text-foreground",
        success: "border-success/35 bg-success/10 text-foreground",
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
