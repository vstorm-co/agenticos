/** A loopback invite works only on the sender's computer, regardless of the app surface. */
export function isLoopbackAddress(value: string): boolean {
  try {
    const host = new URL(value).hostname.toLowerCase();
    return (
      host === "localhost" || host.endsWith(".localhost") || host === "[::1]" || /^127\./.test(host)
    );
  } catch {
    return false;
  }
}
