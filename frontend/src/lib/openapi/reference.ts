/**
 * The public OpenAPI document, read into what the API reference page draws.
 *
 * The document is the backend's public OpenAPI document: only the routes
 * an organization key may call. It is read here rather than rendered by a
 * third-party viewer so the page looks like the rest of the console and works
 * on a deployment with no internet access.
 */

export interface OpenApiSchema {
  $ref?: string;
  type?: string;
  format?: string;
  title?: string;
  description?: string;
  enum?: unknown[];
  items?: OpenApiSchema;
  anyOf?: OpenApiSchema[];
  oneOf?: OpenApiSchema[];
  allOf?: OpenApiSchema[];
  properties?: Record<string, OpenApiSchema>;
  required?: string[];
}

export interface OpenApiParameter {
  name: string;
  in: string;
  required?: boolean;
  description?: string;
  schema?: OpenApiSchema;
}

export interface OpenApiOperation {
  tags?: string[];
  summary?: string;
  description?: string;
  operationId?: string;
  parameters?: OpenApiParameter[];
  requestBody?: { required?: boolean; content?: Record<string, { schema?: OpenApiSchema }> };
  responses?: Record<string, { description?: string }>;
}

export interface OpenApiDocument {
  info: { title: string; version: string; description?: string };
  paths: Record<string, Partial<Record<HttpMethod, OpenApiOperation>>>;
  components?: { schemas?: Record<string, OpenApiSchema> };
}

export const HTTP_METHODS = ["get", "post", "put", "patch", "delete"] as const;
export type HttpMethod = (typeof HTTP_METHODS)[number];

export interface FieldRow {
  name: string;
  location: string | null;
  required: boolean;
  type: string;
  description: string | null;
}

export interface ReferenceOperation {
  id: string;
  method: HttpMethod;
  path: string;
  tag: string;
  summary: string;
  description: string | null;
  parameters: FieldRow[];
  body: FieldRow[];
  bodyType: string | null;
  responses: { status: string; description: string }[];
}

export interface ReferenceGroup {
  tag: string;
  operations: ReferenceOperation[];
}

/**
 * Sent with every call rather than belonging to any one route, so the page says
 * it once at the top instead of in all of the parameter tables.
 */
const ORGANIZATION_HEADER = "x-organization-id";

type Schemas = Record<string, OpenApiSchema>;

function refName(ref: string): string {
  return ref.slice(ref.lastIndexOf("/") + 1);
}

function resolve(schema: OpenApiSchema | undefined, schemas: Schemas): OpenApiSchema | undefined {
  if (schema?.$ref) return schemas[refName(schema.$ref)];
  return schema;
}

/** A schema as one short type label: `string (uuid)`, `AgentRead[]`, `integer | null`. */
export function typeLabel(schema: OpenApiSchema | undefined): string {
  if (!schema) return "any";
  if (schema.$ref) return refName(schema.$ref);
  const union = schema.anyOf ?? schema.oneOf;
  if (union) return union.map(typeLabel).join(" | ");
  if (schema.allOf?.length === 1) return typeLabel(schema.allOf[0]);
  if (schema.enum) return schema.enum.map((value) => JSON.stringify(value)).join(" | ");
  if (schema.type === "array") return `${typeLabel(schema.items)}[]`;
  if (schema.type === "null") return "null";
  if (schema.type) return schema.format ? `${schema.type} (${schema.format})` : schema.type;
  return "any";
}

/** The top-level fields of an object schema, following one `$ref`. */
export function fieldsOf(schema: OpenApiSchema | undefined, schemas: Schemas): FieldRow[] {
  const object = resolve(schema, schemas);
  if (!object?.properties) return [];
  const required = new Set(object.required ?? []);
  return Object.entries(object.properties).map(([name, field]) => ({
    name,
    location: null,
    required: required.has(name),
    type: typeLabel(field),
    description: field.description ?? field.title ?? null,
  }));
}

/** `knowledge-bases` reads as "Knowledge bases"; the acronyms stay acronyms. */
export function humanizeTag(tag: string): string {
  const words = tag
    .split(/[-_\s]+/)
    .map((word) => (["ml", "rag", "api", "mcp"].includes(word) ? word.toUpperCase() : word));
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function readOperation(
  path: string,
  method: HttpMethod,
  operation: OpenApiOperation,
  schemas: Schemas,
): ReferenceOperation {
  const bodySchema = operation.requestBody?.content?.["application/json"]?.schema;
  return {
    id: operation.operationId ?? `${method}-${path}`,
    method,
    path,
    tag: operation.tags?.[0] ?? "other",
    summary: operation.summary ?? path,
    description: operation.description ?? null,
    parameters: (operation.parameters ?? [])
      .filter((parameter) => parameter.name.toLowerCase() !== ORGANIZATION_HEADER)
      .map((parameter) => ({
        name: parameter.name,
        location: parameter.in,
        required: parameter.required ?? false,
        type: typeLabel(parameter.schema),
        description: parameter.description ?? null,
      })),
    body: fieldsOf(bodySchema, schemas),
    bodyType: bodySchema ? typeLabel(bodySchema) : null,
    responses: Object.entries(operation.responses ?? {}).map(([status, response]) => ({
      status,
      description: response.description ?? "",
    })),
  };
}

/** Every operation, grouped by its first tag, groups in the order the document first names them. */
export function buildReference(document: OpenApiDocument): ReferenceGroup[] {
  const schemas = document.components?.schemas ?? {};
  const groups = new Map<string, ReferenceOperation[]>();
  for (const [path, operations] of Object.entries(document.paths)) {
    for (const method of HTTP_METHODS) {
      const operation = operations[method];
      if (!operation) continue;
      const read = readOperation(path, method, operation, schemas);
      groups.set(read.tag, [...(groups.get(read.tag) ?? []), read]);
    }
  }
  return [...groups].map(([tag, operations]) => ({ tag, operations }));
}

/** Whether an operation answers a search: its path, summary or group, case-insensitively. */
export function matchesQuery(operation: ReferenceOperation, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [operation.path, operation.summary, operation.tag, operation.method].some((text) =>
    text.toLowerCase().includes(needle),
  );
}

function placeholder(type: string): string {
  if (type.endsWith("[]")) return "[]";
  if (type.startsWith("integer") || type.startsWith("number")) return "0";
  if (type.startsWith("boolean")) return "false";
  if (type.startsWith("string")) return '"…"';
  return "{}";
}

/** A `curl` call for the operation against `baseUrl`, with a body of its required fields. */
export function curlExample(operation: ReferenceOperation, baseUrl: string): string {
  const lines = [
    `curl -X ${operation.method.toUpperCase()} "${baseUrl}${operation.path}"`,
    '  -H "Authorization: Bearer $AGENTICOS_API_KEY"',
  ];
  if (operation.bodyType) {
    const required = operation.body.filter((field) => field.required);
    const sample = required
      .map((field) => `"${field.name}": ${placeholder(field.type)}`)
      .join(", ");
    lines.push('  -H "Content-Type: application/json"', `  -d '{${sample}}'`);
  }
  return lines.join(" \\\n");
}
