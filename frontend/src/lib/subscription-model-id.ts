/** Remove only AgenticOS account routing; keep the provider's own model namespace. */
export function subscriptionModelId(model: string): string {
  return model.replace(/^account-[a-f0-9]{24}\//, "");
}
