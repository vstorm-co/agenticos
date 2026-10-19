import { ApiError } from "./api-client";
import { parseErrorMessage } from "./api-error";

/**
 * POST a multipart body through the console's BFF, reporting how much of it has gone.
 *
 * XHR rather than `fetch`, because only XHR reports upload progress - which also
 * means going around `apiClient`, so the organization header it would have set
 * is set here: an org-scoped route read without it answers for the personal
 * organization, where the row does not exist.
 *
 * `onPercent` is called with 0-100 as bytes leave, `null` while the browser
 * cannot size the body, and 100 once it is all sent and the server is working.
 * A refusal rejects with an `ApiError` carrying the server's own message, or
 * `failed` where there is none to read.
 */
export function postWithProgress(
  path: string,
  body: FormData,
  {
    organizationId,
    onPercent,
    failed,
  }: { organizationId: string | null; onPercent: (percent: number | null) => void; failed: string },
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.withCredentials = true;
    if (organizationId) xhr.setRequestHeader("X-Organization-Id", organizationId);
    xhr.upload.onprogress = (event) =>
      onPercent(
        event.lengthComputable
          ? Math.min(100, Math.round((event.loaded / event.total) * 100))
          : null,
      );
    xhr.upload.onload = () => onPercent(100);
    xhr.onload = () => {
      let answer: unknown = null;
      try {
        answer = JSON.parse(xhr.responseText);
      } catch {
        // An empty or non-JSON body: nothing to parse a message out of.
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(answer);
      else reject(new ApiError(xhr.status, parseErrorMessage(answer, failed), answer));
    };
    xhr.onerror = () => reject(new ApiError(0, failed));
    xhr.send(body);
  });
}
