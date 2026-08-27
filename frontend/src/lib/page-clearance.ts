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
