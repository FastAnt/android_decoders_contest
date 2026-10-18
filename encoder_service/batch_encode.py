from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import time
import zlib
from pathlib import Path
from typing import Any

# Configure runtimes before TensorFlow/JAX/Magenta imports.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "1")
os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "true")
os.environ.setdefault("TF_GPU_ALLOCATOR", "cuda_malloc_async")
os.environ.setdefault("XLA_PYTHON_CLIENT_PREALLOCATE", "false")

import numpy as np
import tensorflow as tf
from tqdm import tqdm

from magenta_rt import audio
from magenta_rt import spectrostream


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = BASE_DIR / "media/data/input"
DEFAULT_OUTPUT_DIR = BASE_DIR / "media/data/encoded"
DEFAULT_RECONSTRUCTION_DIR = BASE_DIR / "media/data/reconstructed"

CODEC_NAME = "spectrostream_ssv2_48k_stereo"
CONTAINER_FORMAT = "SST1"
SCRIPT_VERSION = "2.1.0-chunked"

SAMPLE_RATE = 48_000
CHANNELS = 2
FRAME_RATE = 25
MAX_RVQ_DEPTH = 64
CODEBOOK_SIZE = 1024
BITS_PER_CODE = 10
CHUNK_FRAMES = 25  # One second per independently checksummed storage chunk.
SAMPLES_PER_CODEC_FRAME = SAMPLE_RATE // FRAME_RATE  # 1920 samples / 40 ms.
DEFAULT_INFERENCE_CHUNK_SECONDS = 8.0
DEFAULT_CONTEXT_SECONDS = 1.0

SUPPORTED_EXTENSIONS = {
    ".wav",
    ".wave",
    ".mp3",
    ".flac",
    ".ogg",
    ".opus",
    ".m4a",
    ".aac",
}

# SST1 global header, little-endian, 64 bytes:
#   char[4] magic = "SST1"
#   uint16 version = 1
#   uint16 header_size = 64
#   uint32 sample_rate = 48000
#   uint16 channels = 2
#   uint16 frame_rate = 25
#   uint16 max_rvq_depth = 64
#   uint16 bits_per_code = 10
#   uint32 chunk_frames = 25
#   uint32 total_frame_count
#   uint64 original_samples
#   uint32 chunk_count
#   uint32 layout = 1 (codebook-major inside each chunk)
#   byte[20] reserved
FILE_HEADER = struct.Struct("<4sHHIHHHHIIQII20s")

# SST1 per-chunk header, little-endian, 16 bytes:
#   uint16 frames_in_chunk
#   uint16 stored_rvq_depth
#   uint32 payload_bytes
#   uint32 payload_crc32
#   uint32 reserved
CHUNK_HEADER = struct.Struct("<HHIII")

MAGIC = b"SST1"
VERSION = 1
LAYOUT_CODEBOOK_MAJOR = 1


def configure_tensorflow(device: str) -> dict[str, Any]:
    """Configure TensorFlow before the SpectroStream model is loaded."""

    physical_gpus = tf.config.list_physical_devices("GPU")

    if device == "cpu":
        tf.config.set_visible_devices([], "GPU")
        selected_device = "cpu"
        visible_gpus: list[tf.config.PhysicalDevice] = []
    else:
        visible_gpus = physical_gpus

        if device == "gpu" and not visible_gpus:
            raise RuntimeError(
                "--device gpu was requested, but TensorFlow sees no GPU. "
                "Check `nvidia-smi` and install `tensorflow[and-cuda]==2.20.0`."
            )

        if visible_gpus:
            for gpu in visible_gpus:
                try:
                    tf.config.experimental.set_memory_growth(gpu, True)
                except RuntimeError as error:
                    raise RuntimeError(
                        "TensorFlow GPU was initialized before memory-growth "
                        "configuration. Restart the Python process."
                    ) from error

            selected_device = "gpu"
        else:
            selected_device = "cpu"

    logical_gpus = tf.config.list_logical_devices("GPU")

    information = {
        "requested_device": device,
        "selected_device": selected_device,
        "tensorflow_version": tf.__version__,
        "physical_gpus": [gpu.name for gpu in physical_gpus],
        "logical_gpus": [gpu.name for gpu in logical_gpus],
    }

    print("TensorFlow:", information["tensorflow_version"])
    print("Requested device:", device)
    print("Selected device:", selected_device)
    print("Physical GPUs:", information["physical_gpus"] or "none")
    print("Logical GPUs:", information["logical_gpus"] or "none")

    return information


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def find_audio_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported audio file: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise FileNotFoundError(input_path)

    return sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def get_track_id(path: Path) -> str:
    """Use a trailing 32-character hexadecimal ID, or a stable hash fallback."""

    match = re.search(r"([0-9a-fA-F]{32})$", path.stem)
    if match:
        return match.group(1).lower()

    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:32]


def get_track_title(path: Path, track_id: str) -> str:
    title = path.stem
    if title.lower().endswith(track_id.lower()):
        title = title[: -len(track_id)].rstrip(" _-")
    return title


def load_audio_with_ffmpeg(
    source: Path,
    max_seconds: float | None,
) -> audio.Waveform:
    """Decode an FFmpeg-supported file into float32 48 kHz stereo PCM."""

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
    ]

    if max_seconds is not None:
        command += ["-t", str(max_seconds)]

    command += [
        "-ac",
        str(CHANNELS),
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_f32le",
        "-f",
        "f32le",
        "pipe:1",
    ]

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if process.returncode != 0:
        error_text = process.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg failed for {source}: {error_text}")

    bytes_per_pcm_frame = CHANNELS * np.dtype("<f4").itemsize
    if len(process.stdout) % bytes_per_pcm_frame != 0:
        raise RuntimeError(
            f"Invalid decoded PCM size for {source}: {len(process.stdout)} bytes"
        )

    samples = np.frombuffer(process.stdout, dtype="<f4").reshape(-1, CHANNELS)
    if samples.shape[0] == 0:
        raise RuntimeError(f"Decoded audio is empty: {source}")

    return audio.Waveform(samples=samples, sample_rate=SAMPLE_RATE)



def _seconds_to_frames(seconds: float, *, minimum: int = 0) -> int:
    frames = int(round(seconds * FRAME_RATE))
    return max(minimum, frames)


def encode_waveform_chunked(
    codec: spectrostream.SpectroStream,
    waveform: audio.Waveform,
    inference_chunk_seconds: float,
    context_seconds: float,
    tensorflow_device: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Encode a long waveform in bounded-memory overlapping chunks.

    Each core interval is surrounded by context. Tokens belonging to the
    context are discarded, and only the core tokens are concatenated.

    Chunk boundaries are aligned to SpectroStream's 25 Hz codec frames.
    """

    if waveform.sample_rate != SAMPLE_RATE:
        raise ValueError(
            f"Expected {SAMPLE_RATE} Hz input, got {waveform.sample_rate}"
        )
    if waveform.num_channels != CHANNELS:
        raise ValueError(
            f"Expected {CHANNELS} channels, got {waveform.num_channels}"
        )

    core_frames_per_chunk = _seconds_to_frames(
        inference_chunk_seconds,
        minimum=1,
    )
    context_frames = _seconds_to_frames(
        context_seconds,
        minimum=0,
    )

    total_frames = math.ceil(
        waveform.num_samples / SAMPLES_PER_CODEC_FRAME
    )

    token_chunks: list[np.ndarray] = []
    chunk_timings: list[dict[str, Any]] = []

    for chunk_index, core_start_frame in enumerate(
        range(0, total_frames, core_frames_per_chunk)
    ):
        core_end_frame = min(
            core_start_frame + core_frames_per_chunk,
            total_frames,
        )

        read_start_frame = max(
            0,
            core_start_frame - context_frames,
        )
        read_end_frame = min(
            total_frames,
            core_end_frame + context_frames,
        )

        read_start_sample = (
            read_start_frame * SAMPLES_PER_CODEC_FRAME
        )
        read_end_sample = min(
            waveform.num_samples,
            read_end_frame * SAMPLES_PER_CODEC_FRAME,
        )

        chunk_waveform = waveform[
            read_start_sample:read_end_sample
        ]

        started = time.perf_counter()
        with tf.device(tensorflow_device):
            chunk_tokens = np.asarray(
                codec.encode(chunk_waveform),
                dtype=np.int32,
            )
        elapsed = time.perf_counter() - started

        if (
            chunk_tokens.ndim != 2
            or chunk_tokens.shape[1] != MAX_RVQ_DEPTH
        ):
            raise RuntimeError(
                f"Unexpected token shape in inference chunk "
                f"{chunk_index}: {chunk_tokens.shape}"
            )

        left_context_frames = (
            core_start_frame - read_start_frame
        )
        core_frame_count = core_end_frame - core_start_frame

        selected = chunk_tokens[
            left_context_frames:
            left_context_frames + core_frame_count
        ]

        if selected.shape != (
            core_frame_count,
            MAX_RVQ_DEPTH,
        ):
            raise RuntimeError(
                f"Chunk {chunk_index} produced insufficient tokens: "
                f"selected={selected.shape}, "
                f"expected=({core_frame_count}, {MAX_RVQ_DEPTH}), "
                f"raw={chunk_tokens.shape}"
            )

        token_chunks.append(
            np.ascontiguousarray(selected, dtype=np.int32)
        )

        chunk_timings.append(
            {
                "index": chunk_index,
                "core_start_frame": core_start_frame,
                "core_frame_count": core_frame_count,
                "read_start_frame": read_start_frame,
                "read_frame_count": (
                    read_end_frame - read_start_frame
                ),
                "encode_seconds": elapsed,
            }
        )

    tokens = np.concatenate(token_chunks, axis=0)

    if tokens.shape != (total_frames, MAX_RVQ_DEPTH):
        raise RuntimeError(
            f"Concatenated token shape mismatch: "
            f"{tokens.shape} != "
            f"({total_frames}, {MAX_RVQ_DEPTH})"
        )

    return tokens, {
        "inference_chunk_seconds": inference_chunk_seconds,
        "context_seconds": context_seconds,
        "core_frames_per_chunk": core_frames_per_chunk,
        "context_frames": context_frames,
        "inference_chunk_count": len(chunk_timings),
        "chunks": chunk_timings,
    }


def decode_tokens_chunked(
    codec: spectrostream.SpectroStream,
    tokens: np.ndarray,
    original_samples: int,
    inference_chunk_seconds: float,
    context_seconds: float,
    tensorflow_device: str,
) -> tuple[audio.Waveform, dict[str, Any]]:
    """Decode tokens with bounded accelerator memory and overlap context."""

    if tokens.ndim != 2:
        raise ValueError(
            f"Expected tokens [frames, depth], got {tokens.shape}"
        )

    core_frames_per_chunk = _seconds_to_frames(
        inference_chunk_seconds,
        minimum=1,
    )
    context_frames = _seconds_to_frames(
        context_seconds,
        minimum=0,
    )

    total_frames = tokens.shape[0]
    pcm_chunks: list[np.ndarray] = []
    chunk_timings: list[dict[str, Any]] = []

    for chunk_index, core_start_frame in enumerate(
        range(0, total_frames, core_frames_per_chunk)
    ):
        core_end_frame = min(
            core_start_frame + core_frames_per_chunk,
            total_frames,
        )

        read_start_frame = max(
            0,
            core_start_frame - context_frames,
        )
        read_end_frame = min(
            total_frames,
            core_end_frame + context_frames,
        )

        chunk_tokens = np.ascontiguousarray(
            tokens[read_start_frame:read_end_frame],
            dtype=np.int32,
        )

        started = time.perf_counter()
        with tf.device(tensorflow_device):
            decoded = codec.decode(chunk_tokens)
        elapsed = time.perf_counter() - started

        left_context_frames = (
            core_start_frame - read_start_frame
        )
        core_frame_count = core_end_frame - core_start_frame

        first_sample = (
            left_context_frames * SAMPLES_PER_CODEC_FRAME
        )
        core_sample_count = (
            core_frame_count * SAMPLES_PER_CODEC_FRAME
        )

        selected = decoded.samples[
            first_sample:first_sample + core_sample_count
        ]

        if selected.shape[0] != core_sample_count:
            raise RuntimeError(
                f"Decoder chunk {chunk_index} produced insufficient "
                f"samples: {selected.shape[0]} != {core_sample_count}"
            )

        pcm_chunks.append(
            np.ascontiguousarray(selected, dtype=np.float32)
        )
        chunk_timings.append(
            {
                "index": chunk_index,
                "core_start_frame": core_start_frame,
                "core_frame_count": core_frame_count,
                "decode_seconds": elapsed,
            }
        )

    samples = np.concatenate(pcm_chunks, axis=0)
    samples = samples[:original_samples]

    if samples.shape != (original_samples, CHANNELS):
        raise RuntimeError(
            f"Decoded PCM shape mismatch: "
            f"{samples.shape} != ({original_samples}, {CHANNELS})"
        )

    return (
        audio.Waveform(samples=samples, sample_rate=SAMPLE_RATE),
        {
            "inference_chunk_seconds": inference_chunk_seconds,
            "context_seconds": context_seconds,
            "inference_chunk_count": len(chunk_timings),
            "chunks": chunk_timings,
        },
    )


def pack_10bit(values: np.ndarray) -> bytes:
    """Pack integer values 0..1023 into a little-endian 10-bit bitstream."""

    flat = np.asarray(values, dtype=np.uint16).reshape(-1)
    if flat.size == 0:
        return b""

    maximum = int(flat.max())
    if maximum >= CODEBOOK_SIZE:
        raise ValueError(f"Token {maximum} is outside the 10-bit range")

    original_count = flat.size
    padding = (-original_count) % 4
    if padding:
        flat = np.pad(flat, (0, padding), mode="constant")

    groups = flat.astype(np.uint64).reshape(-1, 4)
    packed40 = (
        groups[:, 0]
        | (groups[:, 1] << 10)
        | (groups[:, 2] << 20)
        | (groups[:, 3] << 30)
    )

    output = np.empty((groups.shape[0], 5), dtype=np.uint8)
    output[:, 0] = packed40 & 0xFF
    output[:, 1] = (packed40 >> 8) & 0xFF
    output[:, 2] = (packed40 >> 16) & 0xFF
    output[:, 3] = (packed40 >> 24) & 0xFF
    output[:, 4] = (packed40 >> 32) & 0xFF

    required_bytes = (original_count * BITS_PER_CODE + 7) // 8
    return output.reshape(-1)[:required_bytes].tobytes()


def expected_payload_bytes(frame_count: int, rvq_depth: int) -> int:
    return (frame_count * rvq_depth * BITS_PER_CODE + 7) // 8


def write_sst_container(
    destination: Path,
    tokens: np.ndarray,
    original_samples: int,
) -> dict[str, Any]:
    """Write one q64 SST1 file with codebook-major one-second chunks."""

    if tokens.ndim != 2:
        raise ValueError(f"Expected tokens [frames, depth], got {tokens.shape}")

    frame_count, rvq_depth = tokens.shape
    if rvq_depth != MAX_RVQ_DEPTH:
        raise ValueError(
            f"Expected {MAX_RVQ_DEPTH} RVQ layers, got {rvq_depth}"
        )

    if tokens.dtype != np.int32:
        tokens = tokens.astype(np.int32, copy=False)

    if tokens.size:
        token_min = int(tokens.min())
        token_max = int(tokens.max())
        if token_min < 0 or token_max >= CODEBOOK_SIZE:
            raise ValueError(
                f"Invalid token range: min={token_min}, max={token_max}"
            )

    chunk_count = math.ceil(frame_count / CHUNK_FRAMES)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".tmp")

    chunks: list[dict[str, Any]] = []

    try:
        with temporary_path.open("wb") as output:
            output.write(
                FILE_HEADER.pack(
                    MAGIC,
                    VERSION,
                    FILE_HEADER.size,
                    SAMPLE_RATE,
                    CHANNELS,
                    FRAME_RATE,
                    MAX_RVQ_DEPTH,
                    BITS_PER_CODE,
                    CHUNK_FRAMES,
                    frame_count,
                    original_samples,
                    chunk_count,
                    LAYOUT_CODEBOOK_MAJOR,
                    b"\0" * 20,
                )
            )

            for chunk_index, start_frame in enumerate(
                range(0, frame_count, CHUNK_FRAMES)
            ):
                end_frame = min(start_frame + CHUNK_FRAMES, frame_count)
                chunk = tokens[start_frame:end_frame, :]

                # [frames, depth] -> [depth, frames]. The first 16 or 32
                # codebooks therefore form a byte-aligned prefix of each chunk.
                codebook_major = np.ascontiguousarray(chunk.T, dtype=np.uint16)
                payload = pack_10bit(codebook_major)

                expected_size = expected_payload_bytes(
                    chunk.shape[0], MAX_RVQ_DEPTH
                )
                if len(payload) != expected_size:
                    raise AssertionError(
                        f"Payload size mismatch: {len(payload)} != {expected_size}"
                    )

                crc32 = zlib.crc32(payload) & 0xFFFFFFFF
                output.write(
                    CHUNK_HEADER.pack(
                        chunk.shape[0],
                        MAX_RVQ_DEPTH,
                        len(payload),
                        crc32,
                        0,
                    )
                )
                output.write(payload)

                chunks.append(
                    {
                        "index": chunk_index,
                        "first_frame": start_frame,
                        "frame_count": chunk.shape[0],
                        "payload_bytes_q64": len(payload),
                        "payload_crc32": crc32,
                    }
                )

            output.flush()
            os.fsync(output.fileno())

        temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return {
        "file_bytes": destination.stat().st_size,
        "frame_count": frame_count,
        "chunk_count": chunk_count,
        "chunks": chunks,
    }


def validate_sst_container(path: Path) -> dict[str, int]:
    """Validate structure, sizes and CRCs immediately after writing."""

    with path.open("rb") as file:
        raw_header = file.read(FILE_HEADER.size)
        if len(raw_header) != FILE_HEADER.size:
            raise RuntimeError(f"Truncated SST1 header: {path}")

        (
            magic,
            version,
            header_size,
            sample_rate,
            channels,
            frame_rate,
            max_rvq_depth,
            bits_per_code,
            chunk_frames,
            total_frame_count,
            original_samples,
            chunk_count,
            layout,
            _reserved,
        ) = FILE_HEADER.unpack(raw_header)

        expected_values = {
            "magic": (magic, MAGIC),
            "version": (version, VERSION),
            "header_size": (header_size, FILE_HEADER.size),
            "sample_rate": (sample_rate, SAMPLE_RATE),
            "channels": (channels, CHANNELS),
            "frame_rate": (frame_rate, FRAME_RATE),
            "max_rvq_depth": (max_rvq_depth, MAX_RVQ_DEPTH),
            "bits_per_code": (bits_per_code, BITS_PER_CODE),
            "chunk_frames": (chunk_frames, CHUNK_FRAMES),
            "layout": (layout, LAYOUT_CODEBOOK_MAJOR),
        }

        for name, (actual, expected) in expected_values.items():
            if actual != expected:
                raise RuntimeError(
                    f"Invalid {name} in {path}: {actual!r} != {expected!r}"
                )

        counted_frames = 0
        counted_chunks = 0

        for chunk_index in range(chunk_count):
            raw_chunk_header = file.read(CHUNK_HEADER.size)
            if len(raw_chunk_header) != CHUNK_HEADER.size:
                raise RuntimeError(
                    f"Truncated chunk header {chunk_index} in {path}"
                )

            frames, depth, payload_bytes, expected_crc32, _ = CHUNK_HEADER.unpack(
                raw_chunk_header
            )

            if not 1 <= frames <= CHUNK_FRAMES:
                raise RuntimeError(
                    f"Invalid frame count {frames} in chunk {chunk_index}"
                )
            if depth != MAX_RVQ_DEPTH:
                raise RuntimeError(
                    f"Invalid RVQ depth {depth} in chunk {chunk_index}"
                )

            expected_bytes = expected_payload_bytes(frames, depth)
            if payload_bytes != expected_bytes:
                raise RuntimeError(
                    f"Invalid payload size in chunk {chunk_index}: "
                    f"{payload_bytes} != {expected_bytes}"
                )

            payload = file.read(payload_bytes)
            if len(payload) != payload_bytes:
                raise RuntimeError(f"Truncated payload in chunk {chunk_index}")

            actual_crc32 = zlib.crc32(payload) & 0xFFFFFFFF
            if actual_crc32 != expected_crc32:
                raise RuntimeError(
                    f"CRC mismatch in chunk {chunk_index}: "
                    f"{actual_crc32} != {expected_crc32}"
                )

            counted_frames += frames
            counted_chunks += 1

        if counted_frames != total_frame_count:
            raise RuntimeError(
                f"Frame count mismatch: {counted_frames} != {total_frame_count}"
            )
        if counted_chunks != chunk_count:
            raise RuntimeError(
                f"Chunk count mismatch: {counted_chunks} != {chunk_count}"
            )
        if file.read(1):
            raise RuntimeError(f"Unexpected trailing data in {path}")

    return {
        "frame_count": total_frame_count,
        "original_samples": original_samples,
        "chunk_count": chunk_count,
    }


def estimate_stream_size(frame_count: int, rvq_depth: int) -> int:
    """Estimate SST1 bytes if only the first N RVQ codebooks are transferred."""

    if rvq_depth not in (16, 32, 64):
        raise ValueError("Supported stream depths are 16, 32 and 64")

    total_bytes = FILE_HEADER.size
    for start_frame in range(0, frame_count, CHUNK_FRAMES):
        frames = min(CHUNK_FRAMES, frame_count - start_frame)
        total_bytes += CHUNK_HEADER.size
        total_bytes += expected_payload_bytes(frames, rvq_depth)

    return total_bytes


def is_already_encoded(
    source: Path,
    metadata_path: Path,
    container_path: Path,
    max_seconds: float | None,
    inference_chunk_seconds: float,
    context_seconds: float,
) -> bool:
    if not metadata_path.exists() or not container_path.exists():
        return False

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    source_stat = source.stat()
    return (
        metadata.get("status") == "success"
        and metadata.get("source_bytes") == source_stat.st_size
        and metadata.get("source_mtime_ns") == source_stat.st_mtime_ns
        and metadata.get("max_seconds") == max_seconds
        and metadata.get("inference_chunk_seconds")
        == inference_chunk_seconds
        and metadata.get("context_seconds") == context_seconds
        and metadata.get("container_bytes") == container_path.stat().st_size
        and metadata.get("container_format") == CONTAINER_FORMAT
    )


def build_catalog(output_directory: Path) -> dict[str, Any]:
    tracks: list[dict[str, Any]] = []

    for metadata_path in sorted(output_directory.glob("*/metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if metadata.get("status") == "success":
            tracks.append(metadata)

    total_transfer_bytes = {
        f"q{depth}": sum(
            track["stream_variants"][f"q{depth}"]["estimated_transfer_bytes"]
            for track in tracks
        )
        for depth in (16, 32, 64)
    }

    catalog = {
        "codec": CODEC_NAME,
        "container_format": CONTAINER_FORMAT,
        "track_count": len(tracks),
        "total_source_bytes": sum(track["source_bytes"] for track in tracks),
        "total_container_bytes_q64": sum(
            track["container_bytes"] for track in tracks
        ),
        "total_transfer_bytes": total_transfer_bytes,
        "total_duration_seconds": sum(
            track["duration_seconds"] for track in tracks
        ),
        "tracks": tracks,
    }

    atomic_write_json(output_directory / "catalog.json", catalog)
    return catalog


def encode_track(
    codec: spectrostream.SpectroStream,
    source: Path,
    output_directory: Path,
    reconstruction_directory: Path,
    max_seconds: float | None,
    verification_depths: list[int],
    runtime_information: dict[str, Any],
    inference_chunk_seconds: float,
    context_seconds: float,
    tensorflow_device: str,
) -> dict[str, Any]:
    track_id = get_track_id(source)
    title = get_track_title(source, track_id)

    track_directory = output_directory / track_id
    track_directory.mkdir(parents=True, exist_ok=True)

    container_path = track_directory / f"{track_id}.sst"
    metadata_path = track_directory / "metadata.json"
    source_stat = source.stat()

    input_started = time.perf_counter()
    waveform = load_audio_with_ffmpeg(
        source,
        max_seconds=max_seconds,
    )
    input_decode_seconds = time.perf_counter() - input_started
    duration_seconds = waveform.seconds

    encode_started = time.perf_counter()
    tokens, chunked_encode = encode_waveform_chunked(
        codec=codec,
        waveform=waveform,
        inference_chunk_seconds=inference_chunk_seconds,
        context_seconds=context_seconds,
        tensorflow_device=tensorflow_device,
    )
    encode_seconds = time.perf_counter() - encode_started

    container_result = write_sst_container(
        destination=container_path,
        tokens=tokens,
        original_samples=waveform.num_samples,
    )
    validation_result = validate_sst_container(container_path)

    frame_count = tokens.shape[0]
    stream_variants: dict[str, Any] = {}

    for depth in (16, 32, 64):
        transfer_bytes = estimate_stream_size(
            frame_count,
            depth,
        )
        stream_variants[f"q{depth}"] = {
            "rvq_depth": depth,
            "nominal_kbps": (
                FRAME_RATE * depth * BITS_PER_CODE / 1000
            ),
            "estimated_transfer_bytes": transfer_bytes,
            "effective_kbps_with_container": (
                transfer_bytes * 8 / duration_seconds / 1000
            ),
            "compression_vs_source": (
                source_stat.st_size / transfer_bytes
            ),
        }

    verifications: list[dict[str, Any]] = []

    if verification_depths:
        verification_track_directory = (
            reconstruction_directory / track_id
        )
        verification_track_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        for depth in verification_depths:
            decode_started = time.perf_counter()
            reconstructed, chunked_decode = decode_tokens_chunked(
                codec=codec,
                tokens=tokens[:, :depth],
                original_samples=waveform.num_samples,
                inference_chunk_seconds=inference_chunk_seconds,
                context_seconds=context_seconds,
                tensorflow_device=tensorflow_device,
            )
            neural_decode_seconds = (
                time.perf_counter() - decode_started
            )

            reconstruction_path = (
                verification_track_directory
                / f"{track_id}.q{depth}.wav"
            )
            reconstructed.write(
                str(reconstruction_path),
                subtype="PCM_16",
            )

            verifications.append(
                {
                    "rvq_depth": depth,
                    "file": str(reconstruction_path.resolve()),
                    "decode_seconds": neural_decode_seconds,
                    "decode_rtf": (
                        neural_decode_seconds / duration_seconds
                    ),
                    "chunked_decode": chunked_decode,
                }
            )

    metadata = {
        "status": "success",
        "codec": CODEC_NAME,
        "container_format": CONTAINER_FORMAT,
        "track_id": track_id,
        "title": title,
        "source_name": source.name,
        "source_path": str(source.resolve()),
        "source_bytes": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "max_seconds": max_seconds,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "duration_seconds": duration_seconds,
        "original_samples": waveform.num_samples,
        "frame_count": frame_count,
        "container_path": str(container_path.resolve()),
        "container_bytes": container_result["file_bytes"],
        "chunk_count": container_result["chunk_count"],
        "container_validated": (
            validation_result["frame_count"] == frame_count
            and validation_result["original_samples"]
            == waveform.num_samples
        ),
        "input_decode_seconds": input_decode_seconds,
        "encode_seconds": encode_seconds,
        "encode_rtf": encode_seconds / duration_seconds,
        "inference_chunk_seconds": inference_chunk_seconds,
        "context_seconds": context_seconds,
        "chunked_encode": chunked_encode,
        "runtime": runtime_information,
        "stream_variants": stream_variants,
        "verifications": verifications,
    }

    atomic_write_json(metadata_path, metadata)
    (track_directory / "error.json").unlink(missing_ok=True)
    return metadata


def parse_depths(value: str) -> list[int]:
    depths = sorted(
        {
            int(item.strip())
            for item in value.split(",")
            if item.strip()
        }
    )

    invalid = [depth for depth in depths if depth not in (16, 32, 64)]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Supported verification depths: 16,32,64; invalid: {invalid}"
        )

    return depths


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-encode audio into scalable SpectroStream SST1 containers."
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SCRIPT_VERSION}",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--reconstructed",
        type=Path,
        default=DEFAULT_RECONSTRUCTION_DIR,
    )
    parser.add_argument(
        "--device",
        choices=("gpu", "cpu", "auto"),
        default="gpu",
        help="Inference device. Default: gpu (fail if unavailable).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N discovered files.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="Encode only the first N seconds of every source file.",
    )
    parser.add_argument(
        "--inference-chunk-seconds",
        type=float,
        default=DEFAULT_INFERENCE_CHUNK_SECONDS,
        help=(
            "Core inference chunk length. Context is added around it. "
            f"Default: {DEFAULT_INFERENCE_CHUNK_SECONDS} seconds."
        ),
    )
    parser.add_argument(
        "--context-seconds",
        type=float,
        default=DEFAULT_CONTEXT_SECONDS,
        help=(
            "Left/right context around every inference chunk. "
            f"Default: {DEFAULT_CONTEXT_SECONDS} second."
        ),
    )
    parser.add_argument(
        "--verify-first",
        type=int,
        default=0,
        help="Reconstruct the first N newly encoded tracks.",
    )
    parser.add_argument(
        "--verify-depths",
        type=parse_depths,
        default=parse_depths("16,32,64"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-encode files even when matching output already exists.",
    )

    args = parser.parse_args()

    print(f"batch_encode version: {SCRIPT_VERSION}")

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than zero")
    if args.max_seconds is not None and args.max_seconds <= 0:
        parser.error("--max-seconds must be greater than zero")
    if args.verify_first < 0:
        parser.error("--verify-first cannot be negative")
    if args.inference_chunk_seconds <= 0:
        parser.error("--inference-chunk-seconds must be greater than zero")
    if args.context_seconds < 0:
        parser.error("--context-seconds cannot be negative")

    runtime_information = configure_tensorflow(args.device)
    tensorflow_device = (
        "/GPU:0"
        if runtime_information["selected_device"] == "gpu"
        else "/CPU:0"
    )
    runtime_information["tensorflow_device"] = tensorflow_device
    runtime_information["inference_chunk_seconds"] = (
        args.inference_chunk_seconds
    )
    runtime_information["context_seconds"] = args.context_seconds

    args.output.mkdir(parents=True, exist_ok=True)
    args.reconstructed.mkdir(parents=True, exist_ok=True)

    files = find_audio_files(args.input)
    if args.limit is not None:
        files = files[: args.limit]
    if not files:
        raise RuntimeError(f"No audio files found in {args.input}")

    pending: list[Path] = []
    skipped = 0

    for source in files:
        track_id = get_track_id(source)
        track_directory = args.output / track_id
        container_path = track_directory / f"{track_id}.sst"
        metadata_path = track_directory / "metadata.json"

        if (
            not args.force
            and is_already_encoded(
                source=source,
                metadata_path=metadata_path,
                container_path=container_path,
                max_seconds=args.max_seconds,
                inference_chunk_seconds=args.inference_chunk_seconds,
                context_seconds=args.context_seconds,
            )
        ):
            skipped += 1
        else:
            pending.append(source)

    print(f"Discovered: {len(files)}")
    print(f"Already encoded: {skipped}")
    print(f"Pending: {len(pending)}")
    print(
        "Inference chunking: "
        f"{args.inference_chunk_seconds:.2f}s core + "
        f"{args.context_seconds:.2f}s context per side"
    )

    if not pending:
        catalog = build_catalog(args.output)
        print("Nothing to encode.")
        print(f"Catalog tracks: {catalog['track_count']}")
        print(f"Catalog: {args.output / 'catalog.json'}")
        return

    print("Loading SpectroStream encoder, decoder and quantizer...")
    model_started = time.perf_counter()
    codec = spectrostream.SpectroStream(
        max_rvq_depth=MAX_RVQ_DEPTH,
        lazy=False,
    )
    model_load_seconds = time.perf_counter() - model_started
    runtime_information["model_load_seconds"] = model_load_seconds
    print(f"SpectroStream loaded in {model_load_seconds:.2f} s")

    successes = 0
    failures = 0
    verified = 0

    progress = tqdm(pending, unit="track", dynamic_ncols=True)

    for source in progress:
        progress.set_description(source.name[:50])

        verification_depths: list[int] = []
        if verified < args.verify_first:
            verification_depths = args.verify_depths
            verified += 1

        try:
            metadata = encode_track(
                codec=codec,
                source=source,
                output_directory=args.output,
                reconstruction_directory=args.reconstructed,
                max_seconds=args.max_seconds,
                verification_depths=verification_depths,
                runtime_information=runtime_information,
                inference_chunk_seconds=args.inference_chunk_seconds,
                context_seconds=args.context_seconds,
                tensorflow_device=tensorflow_device,
            )

            successes += 1
            q32 = metadata["stream_variants"]["q32"]
            tqdm.write(
                f"OK {metadata['track_id']} | "
                f"{metadata['duration_seconds']:.1f}s | "
                f"encode RTF={metadata['encode_rtf']:.3f} | "
                f"q32={q32['estimated_transfer_bytes'] / 1024:.1f} KiB"
            )

        except KeyboardInterrupt:
            tqdm.write("Interrupted by user; completed files remain valid.")
            break

        except Exception as error:
            failures += 1
            track_id = get_track_id(source)
            error_directory = args.output / track_id
            error_directory.mkdir(parents=True, exist_ok=True)

            atomic_write_json(
                error_directory / "error.json",
                {
                    "status": "failed",
                    "track_id": track_id,
                    "source": str(source.resolve()),
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            tqdm.write(f"FAILED {source.name}: {type(error).__name__}: {error}")

        progress.set_postfix(
            ok=successes,
            failed=failures,
            skipped=skipped,
        )

    catalog = build_catalog(args.output)

    print()
    print(f"Successful in this run: {successes}")
    print(f"Failed in this run: {failures}")
    print(f"Previously encoded: {skipped}")
    print(f"Catalog tracks: {catalog['track_count']}")
    print(f"Catalog: {args.output / 'catalog.json'}")


if __name__ == "__main__":
    main()
