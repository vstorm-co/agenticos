export interface PromptField {
  path: string;
  value: unknown;
  depth: number;
}

/** Body-root paths accepted by the backend's deliberately expression-free resolver. */
export function promptFields(payload: Record<string, unknown>): PromptField[] {
  // A small JSON sample can still be deeply nested. Walk in document order
  // without using its nesting depth as the JavaScript call stack.
  const fields: PromptField[] = [];
  const pending: PromptField[] = [{ path: "", value: payload, depth: -1 }];
  while (pending.length) {
    const field = pending.pop()!;
    if (field.depth >= 0) fields.push(field);
    const parent = field.value;
    if (parent === null || typeof parent !== "object") continue;
    for (const [key, child] of Object.entries(parent).reverse()) {
      let path: string;
      if (Array.isArray(parent)) path = `${field.path}[${key}]`;
      else if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(key))
        path = field.path ? `${field.path}.${key}` : key;
      else path = `${field.path}[${JSON.stringify(key)}]`;
      pending.push({ path, value: child, depth: field.depth + 1 });
    }
  }
  return fields;
}

export function insertPromptField(prompt: string, path: string, start: number, end: number) {
  const reference = `{{${path}}}`;
  return {
    value: prompt.slice(0, start) + reference + prompt.slice(end),
    caret: start + reference.length,
  };
}
