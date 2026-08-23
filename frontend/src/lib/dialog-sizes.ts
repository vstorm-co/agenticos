/**
 * How big a dialog is, decided by what it holds rather than per dialog.
 *
 * The four RAG dialogs disagreed first: `IngestionSettings` was given 768px in
 * two of them and 512px in the one that also carries four fields above it, which
 * is the cramping #940 reported - not a judgement call, a disagreement. Nobody
 * had decided; each had picked.
 *
 * Height was the same story one dimension over, and worse because a wrong height
 * *hides a control*. Forty dialogs held `h-[92vh]`, `max-h-[92vh]`,
 * `max-h-[90vh]`, `max-h-[85vh]` and `max-h-[80vh]` between them, some with a
 * scroll rule and some without: `h-[90vh]` on the trigger wizard was 90% of the
 * viewport whatever step you were on, with six hundred pixels of white under a
 * three-field form (#1069), and the sync wizard's header plus a `max-h-[60vh]`
 * body plus a footer overflowed its own `max-h-[90vh]` on a short window, which
 * `overflow-hidden` then clipped - so the button that advances the wizard was
 * off the bottom of it.
 *
 * So the scale is here and the rule is the comment on each entry. A dialog picks
 * **one width and one shape**, which is also what makes the next one consistent
 * without anybody remembering this file.
 */

/**
 * A question with two answers, or a form of two or three fields.
 *
 * The primitive's own width, so this token is the decision rather than an
 * override - it says "this dialog was looked at and it is small", where seven
 * dialogs used to say `sm:max-w-md` and be narrower than the default for no
 * reason anybody had written down.
 */
export const DIALOG_CONFIRM = "sm:max-w-lg";

/**
 * A form: fields to fill, one thing at a time.
 *
 * A wizard's steps are this - each step is a handful of inputs, and a wider
 * dialog would leave the fields swimming beside the step list.
 */
export const DIALOG_FORM = "sm:max-w-2xl";

/**
 * A form dense enough that 2xl crowds it - several groups of settings, or a
 * form with something to read beside it.
 *
 * `IngestionSettings` is the case: parser, chunker, image description and an
 * embedding key, and the create dialog carries a name, a description, a scope
 * and a key *above* all of that.
 */
export const DIALOG_WIDE = "sm:max-w-3xl";

/**
 * A gallery or a wizard whose step is a grid: cards to choose from, a catalog,
 * a list beside a form.
 *
 * Wide because the content is two-dimensional. A dialog reaching for this to fit
 * a *long* form wants `DIALOG_WIDE` and a scroll instead.
 */
export const DIALOG_BROAD = "sm:max-w-5xl";

/**
 * A workbench: an editor with a file list, a spec with its diff. A page that
 * happens to be in a dialog.
 *
 * The widest rung, and the last - a dialog that wants the whole window wants
 * `DIALOG_WINDOW`, which is a different shape rather than a wider one.
 */
export const DIALOG_CANVAS = "sm:max-w-[80rem]";

/**
 * Content that may outgrow the window: the dialog scrolls as one piece.
 *
 * Simplest of the shapes and right for most. The header scrolls away with the
 * body, so a dialog whose header carries steps or whose footer carries the
 * button that advances them wants `DIALOG_FRAMED` instead.
 */
export const DIALOG_SCROLL = "max-h-[90vh] scrollbar-thin overflow-y-auto";

/**
 * A fixed header, a body that scrolls, and whatever is below it staying put.
 *
 * The body owes itself `min-h-0 flex-1 overflow-y-auto` - a flex child without
 * `min-h-0` refuses to shrink, so the dialog grows past its own ceiling instead
 * of scrolling inside it.
 */
export const DIALOG_COLUMN = "flex max-h-[90vh] min-h-0 flex-col overflow-hidden";

/**
 * The same, at a fixed height rather than a ceiling.
 *
 * For a dialog whose content *is* a pane to work in - an editor, a log, a file
 * list - where a box that resizes with its content is the wrong reading: the
 * height is the design. Everything else wants `DIALOG_COLUMN`, because a height
 * is a floor as much as a cap and a three-field form does not want one (#1069).
 */
export const DIALOG_FILL = "flex h-[90vh] min-h-0 flex-col overflow-hidden";

/**
 * A stepper: a bordered header, a scrolling middle, a bordered footer.
 *
 * `p-0` because the three bands supply their own padding, and the explicit rows
 * are what make the middle the only one that gives - without them the body's row
 * is sized to its content and `overflow-hidden` clips the footer, taking the
 * button that advances the wizard with it. The middle band owes itself
 * `min-h-0 overflow-y-auto`.
 */
export const DIALOG_FRAMED = "max-h-[90vh] grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden p-0";

/**
 * Nearly the whole window, with a gutter.
 *
 * For the two dialogs that are a viewer rather than a form - a file somebody
 * opened, a log of three hundred rows. Both dimensions, so it carries its own
 * width and must not be combined with one of the tokens above.
 */
export const DIALOG_WINDOW =
  "flex h-[calc(100vh-4rem)] max-h-none w-[calc(100vw-4rem)] max-w-none flex-col gap-3 overflow-hidden p-4 sm:max-w-none sm:p-6";
