# Asset

`asset.input@1` verifies an image, audio recording or video that the workflow run
is allowed to read. Its input is a `FileRef` admitted to this run or produced by
this run. A filename, arbitrary URL or file ID from another run grants no access.

The node returns the same durable file reference with metadata inspected from
the bytes: media kind, detected type, byte size, image/video dimensions and
audio/video duration. It refuses forged reference metadata, missing objects,
animated images, unsupported formats and files exceeding the configured limits.

## Configuration

`accepted_kinds` selects one or more of `image`, `audio` and `video`.
`max_bytes` defaults to 50,000,000; `max_pixels` defaults to 40,000,000;
`max_seconds` defaults to 600. Optional `required_input_name` requires the same
file reference under that name in the run input. It cannot be satisfied by a URL.

Supported formats are still PNG, JPEG, WebP and GIF; WAV, FLAC, MP3 and recognized
Ogg audio; and MP4 or WebM with one video stream and at most one audio stream.
An MP4 containing only audio is not accepted as a video. Metadata labels and
file extensions do not bypass decoding or limits.

## Deployment and access

`WORKFLOW_ASSET_INPUT_ENABLED` defaults to false. The permanent node definition
remains registered so stored graphs and outputs remain readable. Disabled
deployments omit it from the add palette and refuse execution. Audio/video
inspection requires `ffprobe`; the backend image and backend CI install ffmpeg.

Inspection accepts only local staged bytes. Audio/video probes have a format
and protocol allowlist, an eight-second deadline, bounded output, two concurrent
inspections per worker event loop, and Linux memory and CPU limits. Failed or
cancelled probes reap their exact child and remove the staged bytes. Images are
bounded before decoding, and cancellation waits for that bounded decode to end.
No provider or model call is made by this node.
