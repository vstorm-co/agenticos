import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Badge } from "./badge";
import { Button, buttonVariants } from "./button";

/**
 * The colour role assignments, as behaviour.
 *
 * These assert which elements are *allowed to name* which tokens, never what
 * those tokens resolve to. Retheming the product is a token edit in
 * globals.css, and a test that pinned `oklch(48% ...)` or `black` would make
 * that change expensive for no safety - the point of the token layer is that
 * the colour can move while the roles cannot.
 *
 * The roles being protected: the primary action is INK (`primary`, near-black
 * on light surfaces, white on dark ones), and the accent (`brand`) never
 * fills a button - it keeps the quieter jobs of links, selection and focus.
 * If a neutral variant grows a fill, or a fill grows the accent, the register
 * collapses and these fail.
 */

const classesOf = (value: string): string[] => value.split(/\s+/).filter(Boolean);

const NEUTRAL_VARIANTS = ["secondary", "outline", "ghost"] as const;

describe("colour roles", () => {
  it("fills the primary action with ink, never the accent", () => {
    const classes = classesOf(buttonVariants({ variant: "default" }));
    expect(classes).toContain("bg-primary");
    expect(classes).not.toContain("bg-brand");
  });

  it.each(NEUTRAL_VARIANTS)("leaves the %s action unfilled by ink or accent", (variant) => {
    const classes = classesOf(buttonVariants({ variant }));
    expect(classes).not.toContain("bg-primary");
    expect(classes).not.toContain("bg-brand");
  });

  it("keeps destructive on its own tone, so 'delete' can never read as 'confirm'", () => {
    const classes = classesOf(buttonVariants({ variant: "destructive" }));
    expect(classes).toContain("bg-destructive");
    expect(classes).not.toContain("bg-primary");
    expect(classes).not.toContain("bg-brand");
  });

  it("steps the primary button's pointer states along explicit tokens", () => {
    // Not `hover:bg-primary/90`: an alpha fade lightens over a white surface
    // and darkens over a graphite one, so one class would drift in opposite
    // directions between the two themes.
    const classes = classesOf(buttonVariants({ variant: "default" }));
    expect(classes).toContain("hover:bg-primary-hover");
    expect(classes).toContain("active:bg-primary-active");
    expect(classes.filter((c) => c.startsWith("hover:bg-primary/"))).toHaveLength(0);
  });

  it("renders a link as accent text rather than any fill", () => {
    const classes = classesOf(buttonVariants({ variant: "link" }));
    expect(classes).toContain("text-brand");
    expect(classes).not.toContain("bg-brand");
    expect(classes).not.toContain("bg-primary");
  });

  it("gives every button variant a distinct appearance", () => {
    const variants = ["default", "destructive", "outline", "secondary", "ghost", "link"] as const;
    const rendered = variants.map((variant) => buttonVariants({ variant }));
    expect(new Set(rendered).size).toBe(variants.length);
  });

  it("paints a default badge from the same ink tokens as the primary button", () => {
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

    for (const token of ["bg-primary", "text-primary-foreground"]) {
      expect(button).toContain(token);
      expect(badge).toContain(token);
    }
  });
});
