"""Stateful G.711 μ-law/8kHz to PCM16 relay conversion without audioop (Python 3.15).

Integer-rate interpolation on input; a box low-pass before decimation on
output. State crosses websocket frames, so packet boundaries do not drop samples.
"""

import struct


def decode_mulaw(value: int) -> int:
    value ^= 0xFF
    magnitude = (((value & 15) << 3) + 132) << ((value >> 4) & 7)
    return 132 - magnitude if value & 128 else magnitude - 132


def encode_mulaw(sample: int) -> int:
    sign = 128 if sample < 0 else 0
    magnitude = min(abs(sample), 32635) + 132
    exponent = min(7, max(0, magnitude.bit_length() - 8))
    return (~(sign | (exponent << 4) | ((magnitude >> (exponent + 3)) & 15))) & 255


class PhoneCodec:
    def __init__(self, *, input_rate: int, output_rate: int) -> None:
        if input_rate not in {8000, 16000, 24000, 48000} or output_rate not in {
            8000,
            16000,
            24000,
            48000,
        }:
            raise ValueError("Telephone relay needs an integer multiple of 8 kHz")
        self._up = input_rate // 8000
        self._down = output_rate // 8000
        self._previous: int | None = None
        self._sum = 0
        self._count = 0

    def incoming(self, mulaw: bytes) -> bytes:
        samples: list[int] = []
        for value in mulaw:
            sample = decode_mulaw(value)
            previous = sample if self._previous is None else self._previous
            for step in range(1, self._up + 1):
                samples.append(round(previous + (sample - previous) * step / self._up))
            self._previous = sample
        return struct.pack(f"<{len(samples)}h", *samples)

    def outgoing(self, pcm: bytes) -> bytes:
        if len(pcm) % 2:
            raise ValueError("PCM16 must contain whole samples")
        output = bytearray()
        for (sample,) in struct.iter_unpack("<h", pcm):
            self._sum += sample
            self._count += 1
            if self._count == self._down:
                output.append(encode_mulaw(round(self._sum / self._down)))
                self._sum = self._count = 0
        return bytes(output)

    def clear_output(self) -> None:
        self._sum = self._count = 0
