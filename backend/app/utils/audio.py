"""WAV helpers: validate uploads and stitch TTS chunks together (stdlib only)."""
from __future__ import annotations

import array
import io
import struct
import sys
import wave
from dataclasses import dataclass

from app.core.errors import BadRequest, PayloadTooLarge, UnsupportedMedia


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    sample_width: int
    frames: int

    @property
    def duration(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0


def read_wav_info(data: bytes) -> WavInfo:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return WavInfo(w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise UnsupportedMedia(
            "Audio must be a valid PCM WAV file (16-bit, mono). The web app records in this format automatically."
        ) from exc


def validate_upload(data: bytes, *, max_bytes: int, max_seconds: float) -> WavInfo:
    if not data:
        raise BadRequest("Empty audio upload")
    if len(data) > max_bytes:
        raise PayloadTooLarge(f"Audio file is larger than the {max_bytes // (1024 * 1024)} MB limit")
    info = read_wav_info(data)
    if info.sample_width != 2 or info.channels != 1:
        raise UnsupportedMedia("Audio must be 16-bit PCM mono WAV")
    if not 8000 <= info.sample_rate <= 48000:
        raise UnsupportedMedia("Audio sample rate must be between 8 kHz and 48 kHz")
    if info.duration > max_seconds:
        raise PayloadTooLarge(f"Audio is longer than the {int(max_seconds)} second limit")
    if info.duration < 0.2:
        raise BadRequest("Audio is too short to contain speech")
    return info


def _parse_wav(data: bytes) -> tuple[int, int, int, int, bytes]:
    """(format tag 1=PCM / 3=float, channels, sample rate, bits per sample, raw sample bytes) of any RIFF/WAVE file."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, fmt, samples = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt " and size >= 16:
            tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", data[body:body + 16])
            if tag == 0xFFFE and size >= 40:  # WAVE_FORMAT_EXTENSIBLE: the real format is in the sub-format GUID
                tag = struct.unpack("<H", data[body + 24:body + 26])[0]
            fmt = (tag, channels, rate, bits)
        elif cid == b"data":
            samples = data[body:body + size] if body + size <= len(data) else data[body:]  # tolerate streamed/truncated sizes
            break
        pos = body + size + (size & 1)
    if fmt is None or samples is None:
        raise ValueError("WAV file has no fmt or data chunk")
    return (*fmt, samples)


def to_pcm16_wav(data: bytes) -> bytes:
    """Return a standard 16-bit PCM WAV for whatever WAV a speech provider sent.

    Bhashini, for example, answers with 32-bit IEEE-float audio, which Python's `wave` module (used to join
    chunks) cannot read. Everything downstream (joining, caching, browsers, tests) can rely on 16-bit PCM.
    Supports PCM 8/16/24/32-bit and float 32/64-bit, any channel count and sample rate.
    """
    tag, channels, rate, bits, raw = _parse_wav(data)
    if tag == 1 and bits == 16:
        return data  # already what we want
    little = sys.byteorder == "little"
    if tag == 3 and bits in (32, 64):
        step, fmt = bits // 8, "f" if bits == 32 else "d"
        count = len(raw) // step
        values = struct.unpack(f"<{count}{fmt}", raw[: count * step])
        pcm = array.array("h", (max(-32768, min(32767, int(v * 32767.0))) for v in values))
    elif tag == 1 and bits == 8:  # unsigned
        pcm = array.array("h", ((b - 128) << 8 for b in raw))
    elif tag == 1 and bits in (24, 32):
        step = bits // 8
        count = len(raw) // step
        pcm = array.array("h", (int.from_bytes(raw[i * step:(i + 1) * step], "little", signed=True) >> (bits - 16) for i in range(count)))
    else:
        raise ValueError(f"unsupported WAV format (tag={tag}, bits={bits})")
    if not little:
        pcm.byteswap()
    usable = len(pcm) - len(pcm) % channels  # whole frames only
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm[:usable].tobytes())
    return out.getvalue()


def concat_wavs(chunks: list[bytes]) -> bytes:
    """Join several WAV files that share the same format into one."""
    if len(chunks) == 1:
        return chunks[0]
    out = io.BytesIO()
    params = None
    with wave.open(out, "wb") as writer:
        for chunk in chunks:
            with wave.open(io.BytesIO(chunk), "rb") as r:
                if params is None:
                    params = r.getparams()
                    writer.setparams(params)
                writer.writeframes(r.readframes(r.getnframes()))
    return out.getvalue()
