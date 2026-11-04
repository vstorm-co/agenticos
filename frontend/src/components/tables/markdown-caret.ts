/** Measure a multiline textarea caret using its actual wrapping and typography. */
export function markdownCaret(input: HTMLTextAreaElement): { top: number; left: number } {
  const mirror = document.createElement("div");
  const style = getComputedStyle(input);
  mirror.style.cssText =
    "position:fixed;visibility:hidden;white-space:pre-wrap;overflow-wrap:break-word;pointer-events:none;";
  for (const property of [
    "box-sizing",
    "width",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "letter-spacing",
    "line-height",
    "padding",
    "border-width",
    "tab-size",
  ]) {
    mirror.style.setProperty(property, style.getPropertyValue(property));
  }
  mirror.textContent = input.value.slice(0, input.selectionStart);
  const caret = document.createElement("span");
  caret.textContent = "\u200b";
  mirror.appendChild(caret);
  document.body.appendChild(mirror);
  const result = {
    top: caret.offsetTop - input.scrollTop + (parseFloat(style.lineHeight) || 28) + 4,
    left: caret.offsetLeft - input.scrollLeft,
  };
  mirror.remove();
  return result;
}
