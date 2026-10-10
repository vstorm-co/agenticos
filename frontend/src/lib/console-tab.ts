import { clientId } from "@/lib/ids";

/**
 * This browser tab, as the change feed attributes a write to it (#2061).
 *
 * Sent on every request and echoed on the change event a write causes, so a
 * page can tell its own saves - which it already has - from the same person's
 * edit in another tab, which it must not overwrite unseen. Opaque and random:
 * it identifies nothing beyond "this tab".
 */
export const CONSOLE_TAB = clientId();

export const CONSOLE_TAB_HEADER = "X-Console-Tab";
