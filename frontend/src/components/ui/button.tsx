import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      // Raised neutral actions stay legible without introducing a second palette.
      variant: {
        default:
          "border border-foreground/10 bg-action text-action-foreground shadow-sm hover:border-foreground/15 hover:bg-action-hover active:bg-action-active",
        destructive:
          "bg-destructive text-destructive-foreground shadow-card hover:bg-destructive/90",
        // Quiet: a faint edge on whatever it sits on, and a fill only under the
        // pointer. A card-coloured block with its own shadow made every secondary
        // action as heavy as the one primary beside it.
        outline:
          "border border-foreground/12 bg-transparent hover:bg-foreground/[0.05] hover:border-foreground/20",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-brand underline-offset-4 hover:text-brand-hover hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3.5 text-[13px]",
        lg: "h-10 px-6",
        icon: "h-9 w-9",
        "icon-sm": "h-7 w-7 [&_svg]:size-3.5",
        "icon-lg": "h-10 w-10",
      },
    },
    // The small secondary buttons - Export CSV, a filter, a period - are lower
    // and set at 12px, so a row of them reads as controls beside the content
    // rather than a second toolbar above it.
    compoundVariants: [
      { variant: "outline", size: "sm", class: "h-8 gap-1.5 px-3 text-xs [&_svg]:size-3.5" },
    ],
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  // i18n-exempt: a generic type parameter, not a text node
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
