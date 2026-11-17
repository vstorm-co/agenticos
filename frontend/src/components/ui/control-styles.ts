/** Visible for keyboard users, including forced-colour mode where shadows disappear. */
export const CONTROL_FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground/60";

export const CONTROL_DISABLED = "disabled:cursor-not-allowed disabled:opacity-50";

export const CONTROL_INVALID =
  "aria-invalid:border-destructive aria-invalid:focus-visible:border-destructive aria-invalid:focus-visible:outline-destructive";

/** Shared surface and states for text fields, selects and multiline fields. */
export const FORM_CONTROL = `${CONTROL_FOCUS} ${CONTROL_DISABLED} ${CONTROL_INVALID} border-input bg-field text-foreground placeholder:text-muted-foreground enabled:hover:border-foreground/30 enabled:hover:bg-control focus-visible:border-foreground/50 w-full min-w-0 rounded-xl border-2 transition-[background-color,border-color,box-shadow,color] duration-[var(--duration-fast)]`;

/** A visible secondary action surface on both the page and a card. */
export const SECONDARY_CONTROL =
  "border-input bg-field text-foreground hover:border-foreground/30 hover:bg-control-hover active:bg-control-active";

/** Shared trigger for toolbar filters, whether single- or multi-select. */
export const FILTER_CONTROL = `${CONTROL_FOCUS} ${SECONDARY_CONTROL} data-[state=open]:border-foreground/50 data-[state=open]:bg-control-active h-9 gap-1.5 rounded-xl px-2.5 py-1 text-[13px] font-normal focus-visible:border-foreground/50`;

/** Highlight stays visible on both card and popover surfaces. */
export const MENU_ITEM_FOCUS =
  "focus:bg-foreground/[0.09] focus:text-foreground data-[highlighted]:bg-foreground/[0.09] focus:[&_.text-muted-foreground]:text-foreground/80 data-[highlighted]:[&_.text-muted-foreground]:text-foreground/80";

/** Command palettes retain the same highlight while focus stays in their search field. */
export const COMMAND_ITEM_FOCUS =
  "aria-selected:bg-foreground/[0.09] aria-selected:text-foreground data-[selected=true]:bg-foreground/[0.09] data-[selected=true]:text-foreground aria-selected:[&_.text-muted-foreground]:text-foreground/80 data-[selected=true]:[&_.text-muted-foreground]:text-foreground/80";
