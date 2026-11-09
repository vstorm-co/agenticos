/**
 * How much room there is under a page, as one class string.
 *
 * A token rather than a literal repeated at each site, for the reason
 * `dialog-sizes.ts` is a token file: two places declaring it is two answers, and
 * four of those is what #933 was. It is not on the scroll container - a page
 * overflows `DeploymentGate`'s `min-h-0` wrapper, so `main`'s padding edge stays
 * buried mid-content, measured at 0px below the last card at every width.
 *
 * The Architect lives in the phone header, so mobile needs only a small
 * content margin and the safe-area inset:
 * `viewportFit: "cover"` makes it 34px on a modern iPhone.
 *
 * Two places use it: `PageTransition`, for every page that scrolls in `main`,
 * and the maintenance screen, which `DeploymentGate` returns *instead of*
 * rendering that wrapper.
 */
export const PAGE_CLEARANCE = "pb-[calc(1rem+var(--safe-bottom))]";

/**
 * The room a page drawing its own bottom edge owes a phone's home indicator.
 *
 * For the pages `PageTransition` leaves to themselves - chat pins its composer
 * to the bottom of its own pane, so `PAGE_CLEARANCE` under it would be empty
 * space below the box. Only the safe-area inset: there is no bar under it.
 */
export const SAFE_AREA_CLEARANCE = "pb-[var(--safe-bottom)] lg:pb-0";
