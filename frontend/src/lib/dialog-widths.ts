/**
 * How wide a dialog is, decided by what it holds rather than per dialog.
 *
 * The four RAG dialogs disagreed: `IngestionSettings` was given 768px in two of
 * them and 512px in the one that also carries four fields above it, which is
 * the cramping #940 reported - not a judgement call, a disagreement. Nobody had
 * decided; each had picked.
 *
 * So the scale is here and the rule is the comment on each entry. A dialog
 * imports one instead of choosing a number, which is also what makes the next
 * one consistent without anybody remembering this file.
 */

/** A question with two answers, or a sentence and a confirm. Nothing to fill in. */
export const DIALOG_CONFIRM = "sm:max-w-lg";

/**
 * A form: fields to fill, one thing at a time.
 *
 * The wizard's steps are this - each step is a handful of inputs, and a wider
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
