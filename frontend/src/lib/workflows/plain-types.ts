/**
 * What kind of value a field holds, in the words a builder uses - "text",
 * "number", "list" - rather than the type tokens the editor checks bindings
 * with (`string:date-time`, `union(object|null)`, a model's own name).
 */
export type PlainType =
  "text" | "number" | "yesNo" | "date" | "id" | "list" | "object" | "empty" | "any";

const UNION = /^union\((.*)\)$/;

/**
 * The plain kind of a type token from `schemaTypeToken`, or of an observed
 * value's `typeOf`. An optional value is the kind it holds when it holds one;
 * a union of several kinds is "any". A named model (`Payload`, `Headers`) is
 * an object.
 */
export function plainType(token: string): PlainType {
  const union = UNION.exec(token);
  if (union !== null) {
    const members = (union[1] as string).split("|").filter((member) => member !== "null");
    const kinds = new Set(members.map(plainType));
    return kinds.size === 1 ? ([...kinds][0] as PlainType) : "any";
  }
  if (token === "string:date-time" || token === "string:date") return "date";
  if (token === "string:uuid") return "id";
  if (token === "string" || token.startsWith("string:")) return "text";
  if (token === "integer" || token === "number") return "number";
  if (token === "boolean") return "yesNo";
  if (token === "array" || token.startsWith("array:")) return "list";
  if (token === "null") return "empty";
  if (token === "unknown") return "any";
  return "object";
}
