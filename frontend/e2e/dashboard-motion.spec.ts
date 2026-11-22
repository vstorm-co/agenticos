import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE });

for (const { preference, system, moving } of [
  { preference: "full", system: "reduce", moving: true },
  { preference: "reduce", system: "no-preference", moving: false },
] as const) {
  test(`dashboard scope motion resolves ${preference} with OS ${system} in actual frames`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: system });
    await page.addInitScript((motion) => {
      localStorage.setItem("motion-storage", JSON.stringify({ state: { motion }, version: 0 }));
    }, preference);
    const response = await page.request.get("/api/agents");
    expect(response.ok()).toBe(true);
    const agents: unknown = await response.json();
    if (
      !agents ||
      typeof agents !== "object" ||
      !("items" in agents) ||
      !Array.isArray(agents.items)
    )
      throw new Error("Expected the seeded agent registry");
    expect(
      agents.items.some(
        (entry: unknown) =>
          entry && typeof entry === "object" && "name" in entry && entry.name === SEEDED_AGENT_NAME,
      ),
    ).toBe(true);
    await page.goto("/dashboard?view=me");
    const strip = page.getByRole("group", { name: "Dashboard view", exact: true });
    await expect(strip).toHaveAttribute("data-indicator-ready");
    await expect(strip.getByRole("button", { name: "Me", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const frames = await strip.evaluate(async (element) => {
      const target = element.querySelector<HTMLButtonElement>('button[aria-pressed="false"]');
      if (!target) throw new Error("Expected another permitted dashboard scope");
      const x = () => {
        const transform = getComputedStyle(element, "::before").transform;
        return transform === "none" ? 0 : new DOMMatrix(transform).m41;
      };
      const initial = x();
      const initialPanel = document.querySelector<HTMLElement>('[data-dashboard-view="me"]');
      if (!initialPanel) throw new Error("Expected the initial personal dashboard");
      const initialAnimation = getComputedStyle(initialPanel).animationName;
      const destination = target.offsetLeft;
      const samples: number[] = [];
      const contentSamples: { x: number; opacity: number }[] = [];
      await new Promise<void>((resolve, reject) => {
        const started = performance.now();
        const sample = (now: number) => {
          samples.push(x());
          const panel = document.querySelector<HTMLElement>("[data-dashboard-view]");
          if (panel && panel !== initialPanel) {
            const style = getComputedStyle(panel);
            contentSamples.push({
              x: style.transform === "none" ? 0 : new DOMMatrix(style.transform).m41,
              opacity: Number(style.opacity),
            });
          }
          const lastPanel = contentSamples.at(-1);
          const settled =
            target.getAttribute("aria-pressed") === "true" &&
            Math.abs(x() - destination) < 0.01 &&
            lastPanel?.x === 0 &&
            lastPanel.opacity === 1;
          // React may commit after the click's first frame on a busy runner.
          // Capture through completion rather than cutting an active transition short.
          if (settled) resolve();
          else if (now - started < 5000) requestAnimationFrame(sample);
          else reject(new Error("Dashboard scope transition did not settle"));
        };
        target.click();
        requestAnimationFrame(sample);
      });
      return { initial, initialAnimation, destination, samples, contentSamples, final: x() };
    });
    expect(frames.initialAnimation).toBe("none");
    expect(frames.destination).toBeGreaterThan(frames.initial + 1);
    expect(frames.final).toBeCloseTo(frames.destination, 0);
    // A declared transition is insufficient: prove that the marker actually
    // passes through positions between its old and new tab, or jumps in Reduce.
    const interpolated = frames.samples.some(
      (x) => x > frames.initial + 0.5 && x < frames.destination - 0.5,
    );
    expect(interpolated).toBe(moving);
    expect(frames.contentSamples.length).toBeGreaterThan(0);
    // Sample the content itself: a moving marker can hide a missing panel
    // transition. Full slides and fades; Reduce displays the destination at once.
    const contentMoves = frames.contentSamples.some(
      (sample) => sample.x > 0.5 && sample.x < 12 && sample.opacity > 0 && sample.opacity < 1,
    );
    expect(contentMoves).toBe(moving);
    expect(frames.contentSamples.at(-1)).toEqual({ x: 0, opacity: 1 });
    if (!moving)
      expect(frames.contentSamples.every((sample) => sample.x === 0 && sample.opacity === 1)).toBe(
        true,
      );
  });
}
