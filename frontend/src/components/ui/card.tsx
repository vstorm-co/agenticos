"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("bg-card text-card-foreground shadow-card rounded-xl border", className)}
      {...props}
    />
  ),
);
Card.displayName = "Card";

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex flex-col space-y-1.5 p-(--card-pad)", className)}
      {...props}
    />
  ),
);
CardHeader.displayName = "CardHeader";

const CardTitle = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("leading-none font-semibold tracking-tight", className)}
      {...props}
    />
  ),
);
CardTitle.displayName = "CardTitle";

/**
 * The line under a card's title, folded to one line when it runs longer.
 *
 * Several of the console's cards explain themselves at length, and stacked
 * under one another they turned a settings page into a wall of text before the
 * first control. One line says what the card is for, as a premium console's
 * cards do; "More", at the end of that line, opens the rest. A short
 * description draws exactly as before - the toggle appears only when the text
 * is cut.
 */
const CardDescription = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, children, ...props }, ref) => {
    const t = useTranslations("common");
    const text = React.useRef<HTMLDivElement>(null);
    const [open, setOpen] = React.useState(false);
    const [cut, setCut] = React.useState(false);
    React.useLayoutEffect(() => {
      const element = text.current;
      if (element === null) return;
      const measure = () => setCut(element.scrollHeight > element.clientHeight + 1);
      measure();
      const observer = new ResizeObserver(measure);
      observer.observe(element);
      return () => observer.disconnect();
    }, [children]);
    return (
      <div
        ref={ref}
        className={cn(
          "text-muted-foreground text-sm",
          !open && "flex items-baseline gap-2",
          className,
        )}
        {...props}
      >
        <div ref={text} className={cn(!open && "line-clamp-1 min-w-0 flex-1")}>
          {children}
        </div>
        {(cut || open) && (
          <button
            type="button"
            onClick={() => setOpen((shown) => !shown)}
            className={cn(
              "text-foreground/70 hover:text-foreground shrink-0 text-xs underline-offset-2 hover:underline",
              open && "mt-0.5",
            )}
          >
            {open ? t("showLess") : t("showMore")}
          </button>
        )}
      </div>
    );
  },
);
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("p-(--card-pad) pt-0", className)} {...props} />
  ),
);
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex items-center p-(--card-pad) pt-0", className)} {...props} />
  ),
);
CardFooter.displayName = "CardFooter";

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
