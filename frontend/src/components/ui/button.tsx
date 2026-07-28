import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      // One ink fill, five neutrals. `default` is the page's single primary
      // action and is drawn in ink - near-black on light surfaces, white on
      // dark ones - the way the OpenAI and ElevenLabs consoles draw theirs.
      // The accent never fills a button; it keeps the quieter jobs (links,
      // selection, focus) so it still means "you are here". Pointer states
      // step along explicit tokens rather than fading the fill with `/90`:
      // an alpha fade lightens over white and darkens over graphite, so one
      // class would drift in opposite directions between themes.
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-card hover:bg-primary-hover active:bg-primary-active",
        destructive:
          "bg-destructive text-destructive-foreground shadow-card hover:bg-destructive/90",
        outline:
          "border border-input bg-card shadow-card hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-brand underline-offset-4 hover:text-brand-hover hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3.5 text-xs",
        lg: "h-10 px-6",
        icon: "h-9 w-9",
        "icon-sm": "h-7 w-7 [&_svg]:size-3.5",
        "icon-lg": "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
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
