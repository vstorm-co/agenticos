import { request } from "node:http";

/**
 * @param {string} address
 * @param {{headers: Record<string, string>, body: string, signal: AbortSignal}} options
 * @returns {Promise<Response>}
 */
export function localRequest(address, options) {
  const endpoint = new URL(address);
  if (
    endpoint.protocol !== "http:" ||
    endpoint.hostname !== "127.0.0.1" ||
    !endpoint.port ||
    endpoint.pathname !== "/mcp" ||
    endpoint.search ||
    endpoint.hash ||
    endpoint.username ||
    endpoint.password
  )
    throw new Error("Outside the owned loopback bridge");
  // Raw HTTP never consults environment proxies or a vendor's global fetch dispatcher.
  return new Promise((resolve, reject) => {
    const operation = request(
      endpoint,
      {
        method: "POST",
        headers: options.headers,
        signal: options.signal,
        agent: false,
        maxHeaderSize: 16384,
      },
      (response) => {
        const headers = new Headers();
        for (let index = 0; index < response.rawHeaders.length; index += 2) {
          const name = response.rawHeaders[index];
          const value = response.rawHeaders[index + 1];
          if (name !== undefined && value !== undefined)
            headers.append(name, value);
        }
        const iterator = response[Symbol.asyncIterator]();
        const body = new ReadableStream({
          async pull(controller) {
            const part = await iterator.next();
            if (part.done) controller.close();
            else if (part.value instanceof Uint8Array)
              controller.enqueue(part.value);
            else
              controller.error(
                new Error("Unsupported loopback response chunk"),
              );
          },
          cancel() {
            response.destroy();
          },
        });
        resolve(
          new Response(body, { status: response.statusCode ?? 500, headers }),
        );
      },
    );
    operation.once("error", reject);
    operation.end(options.body);
  });
}
