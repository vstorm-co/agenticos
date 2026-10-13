/**
 * Which characters a locale groups and points a number with.
 *
 * `Intl.NumberFormat` answers this by formatting a number and labelling the
 * pieces, which is the only place the answer actually lives: a hard-coded
 * `,`/`.` pair is English, and the same figure is `1 234,56` in Polish and
 * `1.234,56` in German. `AnimatedCounter` draws one character per cell rather
 * than calling a formatter, so it has to be told.
 */

export interface NumberSeparators {
  /** Between groups of digits - `,`, `.`, or a narrow no-break space. */
  separator: string;
  /** Between the whole part and the fraction. */
  decimalSeparator: string;
}

/** The English pair, and what every locale falls back to. */
const DEFAULT: NumberSeparators = { separator: ",", decimalSeparator: "." };

/**
 * `locale`'s own separators, or the English pair when it names no locale or
 * the runtime does not recognise the one it names.
 *
 * A locale tag the environment cannot resolve makes `Intl.NumberFormat` throw
 * a `RangeError`, and a separator is not worth a blank page: the figure still
 * reads with the wrong comma, where nothing reads at all with an exception.
 */
export function separatorsFor(locale?: string): NumberSeparators {
  try {
    const parts = new Intl.NumberFormat(locale).formatToParts(1234.5);
    return {
      separator: parts.find((part) => part.type === "group")?.value ?? DEFAULT.separator,
      decimalSeparator:
        parts.find((part) => part.type === "decimal")?.value ?? DEFAULT.decimalSeparator,
    };
  } catch {
    return DEFAULT;
  }
}
