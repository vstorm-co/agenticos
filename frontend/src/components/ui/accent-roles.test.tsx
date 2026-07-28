import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Badge } from "./badge";
import { Button, buttonVariants } from "./button";

/**
 * The accent's role assignments, as behaviour.
 *
 * These assert which elements are *allowed to name* the accent tokens, never
 * what those tokens resolve to. Retheming the product is a one-line change to
 * `--brand-h` in globals.css, and a test that pinned `oklch(48% …)` or `blue`
 * would make that change expensive for no safety — the point of the token
 * layer is that the colour can move while the roles cannot.
 *
 * What is actually protected here: the accent stays scarce. A page has one
 * primary action; if `secondary`, `outline` or `ghost` ever grows an accent
 * fill, the accent stops distinguishing anything and these fail.
 */

const classesOf = (value: string): string[] => value.split(/\s+/).filter(Boolean);

const NEUTRAL_VARIANTS = ["secondary", "outline", "ghost"] as const;

describe("accent roles", () => {
  it("fills only the primary action with the accent", () => {
    expect(classesOf(buttonVariants({ variant: "default" }))).toContain("bg-brand");
  });

  it.each(NEUTRAL_VARIANTS)("leaves the %s action neutral", (variant) => {
    expect(classesOf(buttonVariants({ variant }))).not.toContain("bg-brand");
  });

  it("keeps destructive off the accent, so 'delete' can never read as 'confirm'", () => {
    const classes = classesOf(buttonVariants({ variant: "destructive" }));
    expect(classes).toContain("bg-destructive");
    expect(classes).not.toContain("bg-brand");
  });

  it("steps the primary button's pointer states along the accent ramp", () => {
    // Not `hover:bg-brand/90`: an alpha fade lightens over a cream surface and
    // darkens over a near-black one, so one class would drift in opposite
    // directions between the two themes.
    const classes = classesOf(buttonVariants({ variant: "default" }));
    expect(classes).toContain("hover:bg-brand-hover");
    expect(classes).toContain("active:bg-brand-active");
    expect(classes.filter((c) => c.startsWith("hover:bg-brand/"))).toHaveLength(0);
  });

  it("renders a link as accent text rather than an accent fill", () => {
    const classes = classesOf(buttonVariants({ variant: "link" }));
    expect(classes).toContain("text-brand");
    expect(classes).not.toContain("bg-brand");
  });

  it("gives every button variant a distinct appearance", () => {
    const variants = ["default", "destructive", "outline", "secondary", "ghost", "link"] as const;
    const rendered = variants.map((variant) => buttonVariants({ variant }));
    expect(new Set(rendered).size).toBe(variants.length);
  });

  it("paints a default badge from the same accent tokens as the primary button", () => {
    // The whole point of the exercise: comparable elements match because they
    // name the same role, not because two class lists happen to agree.
    render(
      <>
        <Button>save</Button>
        <Badge>live</Badge>
      </>,
    );

    const button = classesOf(screen.getByRole("button").className);
    const badge = classesOf(screen.getByText("live").className);

    for (const token of ["bg-brand", "text-brand-foreground"]) {
      expect(button).toContain(token);
      expect(badge).toContain(token);
    }
  });
});
