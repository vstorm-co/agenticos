/**
 * A screenshot of the page, for the AI Architect to look at (#2063).
 *
 * The browser's own screen capture, asked to prefer this tab: nothing is
 * captured without the person choosing it in the browser's prompt, and a page
 * cannot photograph itself any other way that shows what the person sees. One
 * frame is taken and the capture stopped at once.
 */

/** The current tab as a PNG, or `null` when the person declined to share it. */
export async function captureThisTab(): Promise<File | null> {
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: false,
      // Chrome's hint to offer this tab first; other browsers ignore it.
      preferCurrentTab: true,
    } as DisplayMediaStreamOptions);
  } catch (error) {
    if (error instanceof DOMException && error.name === "NotAllowedError") return null;
    throw error;
  }
  try {
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (blob === null) return null;
    const stamp = new Date().toISOString().slice(0, 19).replaceAll(":", "-");
    return new File([blob], `screenshot-${stamp}.png`, { type: "image/png" });
  } finally {
    for (const track of stream.getTracks()) track.stop();
  }
}
