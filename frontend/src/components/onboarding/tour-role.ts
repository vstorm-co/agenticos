/**
 * The role row on the walkthrough's first card (#2301).
 *
 * Every agent is told the person's role, so an answer is pitched at a head of
 * sales rather than at nobody - and the first card is the one moment everybody
 * passes. One click, and Settings → Profile holds the rest of what agents know.
 * Plain DOM for the reason the language row is: driver.js draws the popover.
 */
export function appendRoleChoice(
  into: HTMLElement,
  current: string | null,
  label: string,
  roles: readonly string[],
  choose: (role: string) => void,
): void {
  const heading = document.createElement("p");
  heading.className = "tour-role-label";
  heading.textContent = label;
  const row = document.createElement("div");
  row.setAttribute("role", "group");
  row.setAttribute("aria-label", label);
  row.className = "tour-language";
  const buttons = roles.map((role) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = role;
    button.setAttribute("aria-pressed", String(role === current));
    button.addEventListener("click", () => {
      for (const other of buttons) other.setAttribute("aria-pressed", String(other === button));
      choose(role);
    });
    return button;
  });
  row.append(...buttons);
  into.append(heading, row);
}
