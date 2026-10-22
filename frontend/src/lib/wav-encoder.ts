/**
 * Speech as a WAV file: 16 kHz, mono, 16-bit little-endian PCM.
 *
 * What dictation records in by default, in every browser: the one format every
 * speech-to-text provider takes, and the one whose length is its size - 32,000
 * bytes a second - so the server counts the samples rather than trusting a
 * header. It accepts exactly this and nothing else, which is why the composer
 * records raw samples from Web Audio and builds the file itself with these
 * functions rather than asking `MediaRecorder` for a container.
 */

/** The rate the file is written at: what speech models are trained on. */
export const WAV_SAMPLE_RATE = 16_000;
/** The canonical RIFF/WAVE header: RIFF chunk, `fmt ` chunk, `data` chunk header. */
export const WAV_HEADER_BYTES = 44;
/** The type the server accepts for these files. */
export const WAV_TYPE = "audio/wav";

const BYTES_PER_SAMPLE = 2;

/** Average every channel into one. Always a new array, never a view of the input. */
export function mixToMono(channels: readonly Float32Array[]): Float32Array {
  const length = Math.min(...channels.map((channel) => channel.length));
  const mono = new Float32Array(length);
  for (const channel of channels) {
    for (let i = 0; i < length; i += 1) mono[i]! += channel[i]! / channels.length;
  }
  return mono;
}

/**
 * A streaming resampler from `fromRate` to `toRate` - 16 kHz for dictation, the
 * model's input rate for a relayed voice call (#54). Feed it consecutive chunks;
 * each call returns the output samples those chunks complete.
 *
 * Downsampling averages every source sample an output sample spans, which is a
 * crude low-pass: plain decimation would fold the band above half the target
 * rate back into the speech. Upsampling - a context under the target rate, such
 * as a Bluetooth headset's 16 kHz one feeding a 24 kHz model - repeats the
 * nearest earlier sample: a crude hold, but the right length. Window edges are
 * counted from the first sample ever fed in, so chunk boundaries do not drift
 * the rate. The few samples that do not fill a last window are dropped - a
 * fraction of a millisecond.
 */
export function createResampler(
  fromRate: number,
  toRate: number = WAV_SAMPLE_RATE,
): (chunk: Float32Array) => Float32Array {
  const ratio = fromRate / toRate;
  /** Source samples already discarded, before `pending[0]`. */
  let consumed = 0;
  /** Output samples produced so far. */
  let produced = 0;
  let pending = new Float32Array(0);
  return (chunk) => {
    const input = new Float32Array(pending.length + chunk.length);
    input.set(pending);
    input.set(chunk, pending.length);
    const output: number[] = [];
    for (;;) {
      const start = Math.floor(produced * ratio) - consumed;
      const end = Math.max(Math.floor((produced + 1) * ratio) - consumed, start + 1);
      if (end > input.length) break;
      let sum = 0;
      for (let i = start; i < end; i += 1) sum += input[i]!;
      output.push(sum / (end - start));
      produced += 1;
    }
    const drop = Math.floor(produced * ratio) - consumed;
    pending = input.slice(drop);
    consumed += drop;
    return Float32Array.from(output);
  };
}

/** Samples in -1..1 as 16-bit little-endian PCM; anything louder is clipped. */
export function toPcm16(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * BYTES_PER_SAMPLE);
  const view = new DataView(buffer);
  samples.forEach((sample, i) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    // Asymmetric on purpose: 16-bit PCM runs from -32768 to 32767.
    view.setInt16(i * BYTES_PER_SAMPLE, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
  });
  return buffer;
}

/** The 44-byte header for `dataBytes` of 16 kHz mono 16-bit PCM. */
export function wavHeader(dataBytes: number): ArrayBuffer {
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES);
  const view = new DataView(buffer);
  const ascii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };
  ascii(0, "RIFF");
  view.setUint32(4, WAV_HEADER_BYTES - 8 + dataBytes, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true); // the `fmt ` chunk's size, for PCM
  view.setUint16(20, 1, true); // format: integer PCM
  view.setUint16(22, 1, true); // channels
  view.setUint32(24, WAV_SAMPLE_RATE, true);
  view.setUint32(28, WAV_SAMPLE_RATE * BYTES_PER_SAMPLE, true); // bytes a second
  view.setUint16(32, BYTES_PER_SAMPLE, true); // bytes a frame
  view.setUint16(34, BYTES_PER_SAMPLE * 8, true); // bits a sample
  ascii(36, "data");
  view.setUint32(40, dataBytes, true);
  return buffer;
}

/** A WAV file of the PCM chunks `toPcm16` produced, in order. */
export function wavBlob(pcm: readonly ArrayBuffer[]): Blob {
  const dataBytes = pcm.reduce((total, chunk) => total + chunk.byteLength, 0);
  return new Blob([wavHeader(dataBytes), ...pcm], { type: WAV_TYPE });
}
