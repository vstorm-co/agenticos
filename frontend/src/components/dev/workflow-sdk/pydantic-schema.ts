import type { NodeSchema, UISchema } from "@workflowbuilder/sdk";

/**
 * Pydantic v2 `model_json_schema()` output -> the SDK's node schema.
 *
 * The SDK does not accept JSON Schema. Its `NodeSchema` is a subset: `string`,
 * `number`, `boolean`, `object` and arrays of objects; no `$ref`, no `enum`
 * (a fixed choice is an `options` list), no `integer`, no `anyOf`, and no
 * dictionaries. Pydantic emits every one of those, so the adapter resolves what
 * it can and reports what it had to drop rather than dropping it silently.
 */
export interface PydanticSchema {
  title?: string;
  description?: string;
  type?: string | string[];
  properties?: Record<string, PydanticSchema>;
  required?: string[];
  items?: PydanticSchema;
  enum?: (string | number)[];
  default?: unknown;
  anyOf?: PydanticSchema[];
  $ref?: string;
  $defs?: Record<string, PydanticSchema>;
  additionalProperties?: boolean | PydanticSchema;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
}

type SdkField = NodeSchema["properties"][string];

export interface AdaptedSchema {
  schema: NodeSchema;
  /** Defaults Pydantic declared, keyed by property. */
  defaults: Record<string, unknown>;
  /** One line per construct the SDK cannot express, `path: reason`. */
  unsupported: string[];
}

function resolve(node: PydanticSchema, defs: Record<string, PydanticSchema>): PydanticSchema {
  if (!node.$ref) return node;
  const name = node.$ref.replace("#/$defs/", "");
  const target = defs[name];
  if (!target) throw new Error(`unresolved $ref ${node.$ref}`);
  // A property's own keys (default, description) win over the definition's.
  const { $ref: _ref, ...own } = node;
  void _ref;
  return { ...target, ...own };
}

/** `anyOf: [X, {type: "null"}]` is Pydantic's spelling of `X | None`. */
function unwrapOptional(node: PydanticSchema): PydanticSchema {
  if (!node.anyOf) return node;
  const rest = node.anyOf.filter((branch) => branch.type !== "null");
  const [only] = rest;
  if (rest.length !== 1 || !only) return node;
  const { anyOf: _anyOf, ...own } = node;
  void _anyOf;
  return { ...only, ...own };
}

function toField(
  name: string,
  raw: PydanticSchema,
  defs: Record<string, PydanticSchema>,
  unsupported: string[],
): SdkField | null {
  const node = unwrapOptional(resolve(unwrapOptional(raw), defs));
  const label = node.title ?? name;

  if (node.anyOf) {
    unsupported.push(`${name}: anyOf with several non-null branches`);
    return null;
  }
  if (node.enum) {
    return {
      type: "string",
      label,
      options: node.enum.map((value) => ({ label: String(value), value: String(value) })),
    };
  }
  switch (node.type) {
    case "string":
      return {
        type: "string",
        label,
        ...(node.minLength !== undefined && { minLength: node.minLength }),
        ...(node.maxLength !== undefined && { maxLength: node.maxLength }),
        ...(node.pattern !== undefined && { pattern: node.pattern }),
      };
    case "integer":
    case "number":
      return {
        type: "number",
        label,
        ...(node.minimum !== undefined && { minimum: node.minimum }),
        ...(node.maximum !== undefined && { maximum: node.maximum }),
      };
    case "boolean":
      return { type: "boolean", label };
    case "array": {
      const item = node.items ? unwrapOptional(resolve(node.items, defs)) : undefined;
      if (item?.type !== "object" || !item.properties) {
        unsupported.push(`${name}: the SDK only accepts arrays of objects`);
        return null;
      }
      return {
        type: "array",
        label,
        items: { type: "object", properties: toProperties(item, defs, unsupported, name) },
      };
    }
    case "object": {
      if (node.additionalProperties && !node.properties) {
        unsupported.push(`${name}: a dict (additionalProperties) has no SDK equivalent`);
        return null;
      }
      return {
        type: "object",
        label,
        ...(node.required && { required: node.required }),
        properties: toProperties(node, defs, unsupported, name),
      };
    }
    default:
      unsupported.push(`${name}: unsupported type ${JSON.stringify(node.type)}`);
      return null;
  }
}

function toProperties(
  parent: PydanticSchema,
  defs: Record<string, PydanticSchema>,
  unsupported: string[],
  prefix = "",
): Record<string, SdkField> {
  const out: Record<string, SdkField> = {};
  for (const [name, raw] of Object.entries(parent.properties ?? {})) {
    const field = toField(prefix ? `${prefix}.${name}` : name, raw, defs, unsupported);
    if (field) out[name] = field;
  }
  return out;
}

export function adaptPydanticSchema(root: PydanticSchema): AdaptedSchema {
  const defs = root.$defs ?? {};
  const unsupported: string[] = [];
  const properties = toProperties(root, defs, unsupported);
  const defaults: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(root.properties ?? {})) {
    if (raw.default !== undefined && name in properties) defaults[name] = raw.default;
  }
  return {
    schema: {
      type: "object",
      ...(root.required && { required: root.required }),
      // `label` and `description` are the two properties every SDK node carries.
      properties: {
        label: { type: "string" },
        description: { type: "string" },
        ...properties,
      },
    },
    defaults,
    unsupported,
  };
}

/** A flat vertical form over the scalar properties; arrays are left to a custom renderer. */
export function scalarUiSchema(schema: NodeSchema): UISchema {
  const controls = Object.entries(schema.properties)
    .filter(
      ([name, field]) =>
        name !== "label" &&
        name !== "description" &&
        field.type !== "array" &&
        field.type !== "object",
    )
    .map(([name, field]) => ({
      type:
        "options" in field && field.options
          ? "Select"
          : field.type === "boolean"
            ? "Switch"
            : "Text",
      scope: `#/properties/${name}`,
      label: ("label" in field && field.label) || name,
    }));
  return { type: "VerticalLayout", elements: controls } as unknown as UISchema;
}
