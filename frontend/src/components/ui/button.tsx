import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Spinner } from "./spinner";
import { SECONDARY_CONTROL } from "./control-styles";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex touch:min-h-11 touch:min-w-11 touch-manipulation items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors duration-[var(--duration-fast)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground/60 disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 data-[loading=true]:opacity-100 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      // Primary actions carry full contrast; repeated row actions use softer fills.
      variant: {
        default:
          "border border-foreground/10 bg-action text-action-foreground hover:border-foreground/15 hover:bg-action-hover active:bg-action-active",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90 active:bg-destructive/80",
        outline: ["border", SECONDARY_CONTROL],
        secondary:
          "border border-transparent bg-control text-foreground hover:bg-control-hover active:bg-control-active",
        ghost: "text-foreground hover:bg-accent hover:text-accent-foreground active:bg-accent/75",
        link: "text-brand underline-offset-4 hover:text-brand-hover hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3.5 text-[13px]",
        lg: "h-11 px-6",
        icon: "h-9 w-9",
        "icon-sm": "h-8 w-8 [&_svg]:size-3.5",
        "icon-lg": "h-10 w-10",
      },
    },
    // The small secondary buttons - Export CSV, a filter, a period - are lower
    // and set at 13px, so a row of them reads as controls beside the content
    // rather than a second toolbar above it.
    compoundVariants: [
      { variant: "outline", size: "sm", class: "h-8 gap-1.5 px-3 text-[13px] [&_svg]:size-3.5" },
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
  /** Keep the action label and dimensions while preventing repeated submissions. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size,
      asChild = false,
      loading = false,
      disabled,
      children,
      onClick,
      ...props
    },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button";
    const unavailable = disabled || loading;
    return (
      <Comp
        {...props}
        className={cn(buttonVariants({ variant, size, className }), loading && "relative")}
        ref={ref}
        disabled={asChild ? undefined : unavailable}
        aria-disabled={asChild && unavailable ? true : props["aria-disabled"]}
        aria-busy={loading || props["aria-busy"]}
        data-loading={loading || undefined}
        onClick={onClick}
        onClickCapture={
          asChild && unavailable
            ? (event) => {
                event.preventDefault();
                event.stopPropagation();
              }
            : props.onClickCapture
        }
      >
        {loading && !asChild ? (
          <>
            <span className="inline-flex items-center justify-center gap-[inherit] opacity-0">
              {children}
            </span>
            <Spinner className="absolute size-4" aria-hidden="true" />
          </>
        ) : (
          children
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
