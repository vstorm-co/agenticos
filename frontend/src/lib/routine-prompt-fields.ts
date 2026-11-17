export interface PromptField {
  path: string;
  value: unknown;
  depth: number;
}

/** Body-root paths accepted by the backend's deliberately expression-free resolver. */
export function promptFields(payload: Record<string, unknown>): PromptField[] {
  const fields: PromptField[] = [];
  const visit = (value: unknown, path: string, depth: number) => {
    fields.push({ path, value, depth });
    if (value !== null && typeof value === "object") {
      for (const [key, child] of Object.entries(value)) {
        const suffix = Array.isArray(value)
          ? `[${key}]`
          : /^[A-Za-z_][A-Za-z0-9_]*$/.test(key)
            ? `.${key}`
            : `[${JSON.stringify(key)}]`;
        visit(child, `${path}${suffix}`, depth + 1);
      }
    }
  };
  for (const [key, value] of Object.entries(payload))
    visit(value, /^[A-Za-z_][A-Za-z0-9_]*$/.test(key) ? key : `[${JSON.stringify(key)}]`, 0);
  return fields;
}

export function insertPromptField(prompt: string, path: string, start: number, end: number) {
  const reference = `{{${path}}}`;
  return {
    value: prompt.slice(0, start) + reference + prompt.slice(end),
    caret: start + reference.length,
  };
}
