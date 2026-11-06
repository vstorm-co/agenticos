"use client";

import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp, ListFilter, type LucideIcon } from "lucide-react";
import { FILTER_CONTROL, FORM_CONTROL, MENU_ITEM_FOCUS } from "./control-styles";
import { cn } from "@/lib/utils";

const Select = SelectPrimitive.Root;
const SelectGroup = SelectPrimitive.Group;
const SelectValue = SelectPrimitive.Value;

const SelectTrigger = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger> & {
    /**
     * `sm` is a filter in a row of filters: 36px, 13px text, a quieter edge - the
     * height of the filter disclosure and search box beside it.
     */
    size?: "default" | "sm";
    /** Semantic icon; compact toolbar filters default to the filter glyph. */
    icon?: LucideIcon;
  }
>(({ className, children, size = "default", icon, ...props }, ref) => {
  const Icon = icon ?? (size === "sm" ? ListFilter : undefined);
  return (
    <SelectPrimitive.Trigger
      ref={ref}
      className={cn(
        FORM_CONTROL,
        "data-[state=open]:border-foreground/40 data-[state=open]:bg-control touch:min-h-11 flex h-10 touch-manipulation items-center justify-between gap-2 px-3 py-2 text-sm [&>span:first-of-type]:min-w-0 [&>span:first-of-type]:flex-1 [&>span:first-of-type]:truncate [&>span:first-of-type]:text-left [&>span:last-child]:shrink-0",
        size === "sm" && FILTER_CONTROL,
        className,
      )}
      {...props}
    >
      {Icon && <Icon aria-hidden className="size-3.5 shrink-0 opacity-70" strokeWidth={1.75} />}
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown
          className={cn(
            "text-foreground/60 shrink-0 stroke-2",
            size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4",
          )}
        />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
});
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

const SelectScrollUpButton = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-1", className)}
    {...props}
  >
    <ChevronUp className="h-4 w-4" />
  </SelectPrimitive.ScrollUpButton>
));
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName;

const SelectScrollDownButton = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-1", className)}
    {...props}
  >
    <ChevronDown className="h-4 w-4" />
  </SelectPrimitive.ScrollDownButton>
));
SelectScrollDownButton.displayName = SelectPrimitive.ScrollDownButton.displayName;

const SelectContent = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(
  (
    { className, children, position = "popper", sideOffset = 6, collisionPadding = 12, ...props },
    ref,
  ) => (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        ref={ref}
        className={cn(
          "panel text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-98 data-[state=open]:zoom-in-98 data-[side=bottom]:slide-in-from-top-1 data-[side=left]:slide-in-from-right-1 data-[side=right]:slide-in-from-left-1 data-[side=top]:slide-in-from-bottom-1 relative z-50 max-h-[min(24rem,var(--radix-select-content-available-height,24rem))] max-w-[calc(100vw-1.5rem)] min-w-[8rem] origin-[var(--radix-select-content-transform-origin)] overflow-hidden rounded-xl",
          className,
        )}
        position={position}
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        {...props}
      >
        <SelectScrollUpButton />
        <SelectPrimitive.Viewport
          className={cn(
            "overscroll-contain p-1.5",
            position === "popper" &&
              "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]",
          )}
        >
          {children}
        </SelectPrimitive.Viewport>
        <SelectScrollDownButton />
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  ),
);
SelectContent.displayName = SelectPrimitive.Content.displayName;

const SelectLabel = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("px-2 py-1.5 text-sm font-semibold", className)}
    {...props}
  />
));
SelectLabel.displayName = SelectPrimitive.Label.displayName;

/**
 * One option.
 *
 * `children` is the option's text, and Radix mirrors it into `SelectValue`: the
 * closed trigger draws whatever an item drew, which is how a brand mark reaches
 * the trigger for free. The same mechanism is why a badge that only makes sense
 * against the other options - a tick meaning "this one already has a key" - must
 * not go in `children`, where the trigger would repeat it as if it meant
 * "selected". `trailing` renders outside `ItemText`, so it stays in the list;
 * give it `ml-auto` to put it at the right-hand edge of the content box, which
 * `pr-8` keeps clear of the selected-item indicator.
 *
 * One thing `children` costs: an item with no `textValue` takes its
 * type-to-search key from its own `textContent`, so children carrying anything
 * but the label - a brand mark's `<title>`, a monogram's initial - need
 * `textValue` as well. See `ProviderRow`.
 */
const SelectItem = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & { trailing?: React.ReactNode }
>(({ className, children, trailing, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      MENU_ITEM_FOCUS,
      "data-[state=checked]:bg-foreground/[0.05] touch:min-h-11 relative flex min-h-9 w-full cursor-pointer touch-manipulation items-center rounded-lg py-2 pr-9 pl-3 text-[13px] outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[state=checked]:font-medium",
      className,
    )}
    {...props}
  >
    <span className="absolute right-3 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-3.5 w-3.5" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    {trailing}
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;

const SelectSeparator = React.forwardRef<
  React.ComponentRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("bg-muted -mx-1 my-1 h-px", className)}
    {...props}
  />
));
SelectSeparator.displayName = SelectPrimitive.Separator.displayName;

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
};
