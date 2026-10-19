/**
 * One shape for every action under a turn - copy, regenerate, pin, the ratings.
 *
 * Copy and regenerate sat on grey squares while the ratings had none, at two
 * sizes and two icon weights, so the row read as three components. A clear
 * square of one size with the fill on hover is the quiet row every chat app
 * settled on.
 */
export const TURN_ACTION =
  "text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] inline-flex h-7 w-7 items-center justify-center gap-1 rounded-lg transition-colors [&_svg]:size-3.5";
