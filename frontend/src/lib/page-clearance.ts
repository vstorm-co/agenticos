/**
 * How much room there is under a page, as one class string.
 *
 * A token rather than a literal repeated at each site, for the reason
 * `dialog-sizes.ts` is a token file: two places declaring it is two answers, and
 * four of those is what #933 was. It is not on the scroll container - a page
 * overflows `DeploymentGate`'s `min-h-0` wrapper, so `main`'s padding edge stays
 * buried mid-content, measured at 0px below the last card at every width.
 *
 * The mobile figure leaves the last card clear of the Architect's button in the
 * corner, and counts the safe-area inset rather than assuming it away:
 * `viewportFit: "cover"` makes it 34px on a modern iPhone.
 *
 * Two places use it: `PageTransition`, for every page that scrolls in `main`,
 * and the maintenance screen, which `DeploymentGate` returns *instead of*
 * rendering that wrapper.
 */
export const PAGE_CLEARANCE = "pb-[calc(5rem+var(--safe-bottom))] lg:pb-16";

/**
 * The room a page drawing its own bottom edge owes a phone's home indicator.
 *
 * For the pages `PageTransition` leaves to themselves - chat pins its composer
 * to the bottom of its own pane, so `PAGE_CLEARANCE` under it would be empty
 * space below the box. Only the safe-area inset: there is no bar under it.
 */
export const SAFE_AREA_CLEARANCE = "pb-[var(--safe-bottom)] lg:pb-0";
