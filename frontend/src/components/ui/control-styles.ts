/** Shared surface and states for text fields, selects and multiline fields. */
export const FORM_CONTROL =
  "border-input bg-field text-foreground placeholder:text-muted-foreground hover:border-foreground/30 focus-visible:border-foreground/50 focus-visible:ring-foreground/15 aria-invalid:border-destructive aria-invalid:focus-visible:border-destructive aria-invalid:focus-visible:ring-destructive w-full min-w-0 rounded-lg border transition-colors duration-[var(--duration-fast)] focus-visible:ring-[3px] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50";

/** A visible secondary action surface on both the page and a card. */
export const SECONDARY_CONTROL =
  "border-input bg-field text-foreground hover:border-foreground/30 hover:bg-control-hover active:bg-control-active";

/** Shared trigger for toolbar filters, whether single- or multi-select. */
export const FILTER_CONTROL = `${SECONDARY_CONTROL} data-[state=open]:border-foreground/35 data-[state=open]:bg-control-active h-9 gap-1.5 rounded-lg px-2.5 py-1 text-[13px] font-normal focus-visible:border-foreground/50 focus-visible:ring-foreground/15 focus-visible:ring-[3px] focus-visible:outline-none`;

/** Highlight stays visible on both card and popover surfaces. */
export const MENU_ITEM_FOCUS =
  "focus:bg-foreground/[0.09] focus:text-foreground data-[highlighted]:bg-foreground/[0.09] focus:[&_.text-muted-foreground]:text-foreground/80 data-[highlighted]:[&_.text-muted-foreground]:text-foreground/80";

/** Command palettes retain the same highlight while focus stays in their search field. */
export const COMMAND_ITEM_FOCUS =
  "aria-selected:bg-foreground/[0.09] aria-selected:text-foreground data-[selected=true]:bg-foreground/[0.09] data-[selected=true]:text-foreground aria-selected:[&_.text-muted-foreground]:text-foreground/80 data-[selected=true]:[&_.text-muted-foreground]:text-foreground/80";
