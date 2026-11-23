/** Visible for keyboard users, including forced-colour mode where shadows disappear. */
export const CONTROL_FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

export const CONTROL_DISABLED = "disabled:cursor-not-allowed disabled:opacity-50";

/** Search chrome keeps its focus marker inside the clipped overlay edge. */
export const SEARCH_FIELD_FOCUS =
  "has-[:focus-visible]:outline-2 has-[:focus-visible]:-outline-offset-2 has-[:focus-visible]:outline-ring";

export const CONTROL_INVALID =
  "aria-invalid:border-destructive aria-invalid:focus-visible:border-destructive aria-invalid:focus-visible:outline-destructive";

/** Shared surface and states for text fields, selects and multiline fields. */
export const FORM_CONTROL = `${CONTROL_FOCUS} ${CONTROL_DISABLED} ${CONTROL_INVALID} border-field-border bg-field text-foreground placeholder:text-muted-foreground enabled:hover:border-foreground/50 enabled:hover:bg-control focus-visible:border-foreground/50 w-full min-w-0 rounded-xl border transition-[background-color,border-color,box-shadow,color] duration-[var(--duration-fast)]`;

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

/** Floating surfaces share their appearance across routes, including portals. */
export const FLOATING_PANEL =
  "panel text-popover-foreground rounded-2xl duration-[var(--duration-panel)] data-[state=closed]:duration-120";

/** Geometry and states shared by menu actions, choices and command results. */
export const MENU_ROW =
  "touch:min-h-11 relative flex min-h-9 cursor-default touch-manipulation items-center gap-2 rounded-xl px-2.5 py-2 text-[13px] outline-none select-none transition-colors duration-[var(--duration-fast)] [&[data-disabled]:not([data-disabled=false])]:pointer-events-none [&[data-disabled]:not([data-disabled=false])]:opacity-50 [&>svg]:pointer-events-none [&>svg]:size-4 [&>svg]:shrink-0";

export const MENU_LABEL = "text-muted-foreground px-2.5 py-2 text-xs font-medium";
export const MENU_SEPARATOR = "bg-border mx-1 my-1 h-px";

/** A disclosure is an action, not another bordered field. */
// i18n-exempt: Tailwind control class tokens, never rendered as interface copy.
export const DISCLOSURE_TRIGGER = `${CONTROL_FOCUS} text-muted-foreground hover:bg-muted/45 hover:text-foreground active:bg-muted/60 touch:min-h-11 flex min-h-9 w-fit max-w-full items-center gap-2 rounded-md px-2 text-left text-[13px] font-medium transition-colors duration-[var(--duration-fast)]`;

export const CHOICE_SURFACE =
  "border-input bg-field inline-flex max-w-full items-center gap-0.5 rounded-xl border p-0.5";
// i18n-exempt: Tailwind control class tokens, never rendered as interface copy.
export const CHOICE_OPTION = `${CONTROL_FOCUS} ${CONTROL_DISABLED} touch:min-h-11 touch:min-w-11 inline-flex min-h-9 touch-manipulation items-center justify-center gap-1.5 rounded-lg px-3 py-1 text-[13px] transition-colors duration-[var(--duration-fast)]`;

/** Native radio/checkbox controls in rich choice cards keep browser semantics. */
// i18n-exempt: Tailwind control class tokens, never rendered as interface copy.
export const NATIVE_CHOICE = `${CONTROL_FOCUS} accent-foreground shrink-0 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50`;

/** Page links and in-page tabs share a visual language, not ARIA roles. */
export const TAB_TRIGGER = `${CONTROL_FOCUS} touch:min-h-11 inline-flex min-h-9 shrink-0 touch-manipulation items-center justify-center gap-2 rounded-t-lg border-b-2 border-transparent px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors duration-[var(--duration-fast)] hover:bg-foreground/[0.04] hover:text-foreground`;

/** Primary destinations and recent projects share one navigation rhythm and selection. */
export const SIDEBAR_NAV_LINK = `${CONTROL_FOCUS} sidebar-nav-link touch:min-h-11 relative flex h-9 shrink-0 items-center rounded-lg text-sm font-normal text-foreground/80 transition-colors duration-[var(--duration-fast)] focus-visible:-outline-offset-2 hover:bg-foreground/5 hover:text-foreground aria-[current=page]:bg-accent aria-[current=page]:font-medium aria-[current=page]:text-foreground aria-[current=page]:hover:bg-accent`;
