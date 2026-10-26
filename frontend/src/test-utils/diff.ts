import type { MatcherFunction } from "@testing-library/react";

/**
 * A diff line by its whole text: changed words are marked inside a line, so the
 * line is no longer one text node a plain string matcher can find.
 */
export function diffLine(text: string | RegExp): MatcherFunction {
  return (_content, element) =>
    element?.tagName === "TD" &&
    (typeof text === "string"
      ? element.textContent === text
      : text.test(element.textContent ?? ""));
}
