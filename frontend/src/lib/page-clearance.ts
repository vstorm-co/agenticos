/**
 * How much room there is under a page, as one class string.
 *
 * A token rather than a literal repeated at each site, for the reason
 * `dialog-sizes.ts` is a token file: two places declaring it is two answers, and
 * four of those is what #933 was. It is not on the scroll container - a page
 * overflows `DeploymentGate`'s `min-h-0` wrapper, so `main`'s padding edge stays
 * buried mid-content, measured at 0px below the last card at every width.
 *
 * The mobile figure counts the safe-area inset rather than assuming it away:
 * `viewportFit: "cover"` makes it 34px on a modern iPhone and the tab bar is
 * `min-h-[56px]` plus that, so a flat 80px leaves the last ten pixels of a page
 * under the bar. The bar is `lg:hidden`, so `lg` needs no inset.
 *
 * Two places use it: `PageTransition`, for every page that scrolls in `main`,
 * and the maintenance screen, which `DeploymentGate` returns *instead of*
 * rendering that wrapper.
 */
export const PAGE_CLEARANCE = "pb-[calc(5rem+env(safe-area-inset-bottom))] lg:pb-16";

/**
 * The room a page drawing its own bottom edge owes the mobile tab bar.
 *
 * For the pages `PageTransition` leaves to themselves - chat pins its composer
 * to the bottom of its own pane, so `PAGE_CLEARANCE` under it would be empty
 * space below the box. With neither, the composer's action row sat under the
 * bar on a phone, send button included. The bar is `min-h-[56px]` and a 1px
 * border, plus the inset; `lg` has no bar.
 */
export const TAB_BAR_CLEARANCE = "pb-[calc(3.5rem+1px+env(safe-area-inset-bottom))] lg:pb-0";
