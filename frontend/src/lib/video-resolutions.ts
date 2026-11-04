/**
 * How tall a video resolution is, so two can be compared - the console's copy of
 * `resolution_lines` in `backend/app/services/video_models.py`.
 *
 * The catalog lists a model's resolutions default first, not in order, and in
 * the providers' own names: `720p` is 720 lines and `4k` is 2160. A name of
 * neither shape reads as 0, which sorts it first and offers it under no ceiling;
 * the server refuses the same name, and a backend test holds every catalog entry
 * to one of the two shapes.
 */
export function resolutionLines(resolution: string): number {
  const [, count, unit] = /^\s*(\d+)(p|k)\s*$/i.exec(resolution) ?? [];
  if (unit === undefined) return 0;
  return unit.toLowerCase() === "p" ? Number(count) : Number(count) * 540;
}

/** The resolutions at least as tall as `lowest`, shortest first - what a ceiling may be. */
export function resolutionsFrom(resolutions: string[], lowest: string): string[] {
  const floor = resolutionLines(lowest);
  return resolutions
    .filter((entry) => resolutionLines(entry) >= floor)
    .sort((a, b) => resolutionLines(a) - resolutionLines(b));
}
