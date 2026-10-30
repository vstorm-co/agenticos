/**
 * Where a chat attachment is read from. Its own module, with nothing imported,
 * so the device's offline copy (`lib/offline`) can name it without pulling in
 * the API client - which reaches the stores, which wipe that copy.
 */
export function getFileUrl(fileId: string): string {
  return `/api/files/${fileId}`;
}
