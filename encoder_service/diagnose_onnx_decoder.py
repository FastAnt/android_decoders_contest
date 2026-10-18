#!/usr/bin/env python3
"""Diagnose TensorFlow vs ONNX SpectroStream decoder differences.

Uses:
  - the existing spectrostream_decoder_spectrum.onnx
  - the real SST file and exported RVQ codebooks
  - TensorFlow's original decoder suffix (Complex + IRFFT + overlap-add)

This tells us whether the observed spectrum differences materially affect PCM.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tf
from tensorflow.python.framework.convert_to_constants import (
    convert_variables_to_constants_v2,
)

from magenta_rt import spectrostream


BASE = Path(__file__).resolve().parent.parent
DEFAULT_MODELS = BASE / "decoder_cpp/models"
DEFAULT_SST = (
    BASE
    / "media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f"
    / "069569e7525fdd1e462b9f5b1a394a9f.sst"
)

FILE_HEADER = struct.Struct("<4sHHIHHHHIIQII20s")
CHUNK_HEADER = struct.Struct("<HHIII")


def tensor_name(reference: str) -> str:
    reference = reference.lstrip("^")
    return reference if ":" in reference else f"{reference}:0"


def extract_single_tensor(value: Any) -> tf.Tensor:
    if isinstance(value, dict):
        if len(value) != 1:
            raise RuntimeError(f"Expected one output, got {list(value)}")
        value = next(iter(value.values()))
    elif isinstance(value, (tuple, list)):
        if len(value) != 1:
            raise RuntimeError(f"Expected one output, got {len(value)}")
        value = value[0]
    return value if tf.is_tensor(value) else tf.convert_to_tensor(value)


class DecoderModule(tf.Module):
    def __init__(self, decoder: Any) -> None:
        super().__init__()
        self.decoder = decoder

        @tf.function(
            input_signature=[
                tf.TensorSpec([1, None, 256], tf.float32, name="embeddings")
            ],
            autograph=False,
        )
        def decode(embeddings: tf.Tensor) -> dict[str, tf.Tensor]:
            audio = extract_single_tensor(self.decoder(embeddings))
            return {"audio": tf.identity(tf.cast(audio, tf.float32), name="audio")}

        self.decode = decode


def unpack_10bit(payload: bytes, count: int) -> np.ndarray:
    """Unpack little-endian continuous 10-bit values."""
    data = np.frombuffer(payload, dtype=np.uint8)
    required_bytes = (count * 10 + 7) // 8
    if data.size < required_bytes:
        raise RuntimeError(
            f"Payload too small: {data.size} < {required_bytes}"
        )

    padded_size = ((required_bytes + 4) // 5) * 5
    padded = np.zeros(padded_size, dtype=np.uint8)
    padded[:required_bytes] = data[:required_bytes]
    groups = padded.reshape(-1, 5).astype(np.uint64)

    packed = (
        groups[:, 0]
        | (groups[:, 1] << 8)
        | (groups[:, 2] << 16)
        | (groups[:, 3] << 24)
        | (groups[:, 4] << 32)
    )

    values = np.empty((groups.shape[0], 4), dtype=np.uint16)
    values[:, 0] = packed & 0x3FF
    values[:, 1] = (packed >> 10) & 0x3FF
    values[:, 2] = (packed >> 20) & 0x3FF
    values[:, 3] = (packed >> 30) & 0x3FF
    return values.reshape(-1)[:count]


def read_first_sst_chunk(path: Path, frame_limit: int) -> np.ndarray:
    with path.open("rb") as stream:
        raw_header = stream.read(FILE_HEADER.size)
        if len(raw_header) != FILE_HEADER.size:
            raise RuntimeError("Truncated SST file header")

        (
            magic,
            version,
            header_size,
            sample_rate,
            channels,
            frame_rate,
            max_depth,
            bits_per_code,
            chunk_frames,
            total_frames,
            original_samples,
            chunk_count,
            layout,
            _reserved,
        ) = FILE_HEADER.unpack(raw_header)

        if magic != b"SST1":
            raise RuntimeError(f"Unexpected SST magic: {magic!r}")
        if version != 1 or header_size != FILE_HEADER.size:
            raise RuntimeError(
                f"Unsupported SST version/header: {version}/{header_size}"
            )
        if (
            sample_rate != 48000
            or channels != 2
            or frame_rate != 25
            or max_depth != 64
            or bits_per_code != 10
            or layout != 1
        ):
            raise RuntimeError(
                "Unexpected SST parameters: "
                f"sr={sample_rate}, ch={channels}, fps={frame_rate}, "
                f"depth={max_depth}, bits={bits_per_code}, layout={layout}"
            )

        raw_chunk_header = stream.read(CHUNK_HEADER.size)
        if len(raw_chunk_header) != CHUNK_HEADER.size:
            raise RuntimeError("SST contains no chunk")

        frames, depth, payload_bytes, expected_crc, _ = CHUNK_HEADER.unpack(
            raw_chunk_header
        )
        if depth != 64:
            raise RuntimeError(f"Unexpected chunk depth: {depth}")

        payload = stream.read(payload_bytes)
        if len(payload) != payload_bytes:
            raise RuntimeError("Truncated SST payload")

        actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise RuntimeError(
                f"CRC mismatch: {actual_crc:#x} != {expected_crc:#x}"
            )

    values = unpack_10bit(payload, frames * depth)
    codebook_major = values.reshape(depth, frames)
    tokens = codebook_major.T.astype(np.int32, copy=False)
    return np.ascontiguousarray(tokens[:frame_limit])


def tokens_to_embeddings(
    tokens: np.ndarray,
    codebooks: np.ndarray,
) -> np.ndarray:
    if tokens.ndim != 2 or tokens.shape[1] != 64:
        raise RuntimeError(f"Unexpected token shape: {tokens.shape}")
    if codebooks.shape != (64, 1024, 256):
        raise RuntimeError(f"Unexpected codebooks shape: {codebooks.shape}")

    result = np.zeros((tokens.shape[0], 256), dtype=np.float32)
    for layer in range(64):
        result += codebooks[layer, tokens[:, layer]]
    return result[np.newaxis, ...]


def freeze_decoder():
    codec = spectrostream.SpectroStream(max_rvq_depth=64, lazy=True)
    module = DecoderModule(codec._decoder)
    concrete = module.decode.get_concrete_function()

    frozen = convert_variables_to_constants_v2(
        concrete,
        lower_control_flow=False,
    )
    graph_def = frozen.graph.as_graph_def(add_shapes=True)

    data_inputs = [
        tensor.name for tensor in frozen.inputs if tensor.dtype != tf.resource
    ]
    if len(data_inputs) != 1:
        raise RuntimeError(f"Unexpected frozen inputs: {data_inputs}")

    complex_nodes = [node for node in graph_def.node if node.op == "Complex"]
    irfft_nodes = [
        node for node in graph_def.node
        if node.op in {"IRFFT", "IRFFT2D", "IRFFT3D"}
    ]
    if len(complex_nodes) != 1 or len(irfft_nodes) != 1:
        raise RuntimeError(
            f"Expected one Complex and one IRFFT, got "
            f"{len(complex_nodes)} and {len(irfft_nodes)}"
        )

    complex_node = complex_nodes[0]
    real_name = tensor_name(complex_node.input[0])
    imag_name = tensor_name(complex_node.input[1])
    input_name = data_inputs[0]

    output_tensors = [
        tensor for tensor in frozen.outputs if tensor.dtype != tf.resource
    ]
    if len(output_tensors) != 1:
        raise RuntimeError(
            f"Expected one frozen output, got {[t.name for t in output_tensors]}"
        )
    audio_name = output_tensors[0].name

    def import_graph() -> None:
        tf.compat.v1.import_graph_def(graph_def, name="")

    wrapped = tf.compat.v1.wrap_function(import_graph, [])
    graph = wrapped.graph

    input_tensor = graph.get_tensor_by_name(input_name)
    real_tensor = graph.get_tensor_by_name(real_name)
    imag_tensor = graph.get_tensor_by_name(imag_name)
    audio_tensor = graph.get_tensor_by_name(audio_name)

    full_fn = wrapped.prune(
        feeds=[input_tensor],
        fetches=[audio_tensor],
    )
    cut_fn = wrapped.prune(
        feeds=[input_tensor],
        fetches=[real_tensor, imag_tensor],
    )
    # Build an independent iSTFT suffix graph.
    # Frozen TensorFlow leaves control-only dependencies back to the original
    # embeddings placeholder. They are irrelevant after variables are frozen,
    # but prevent WrappedFunction.prune() from splitting the graph.
    import copy

    suffix_graph_def = copy.deepcopy(graph_def)

    removed_control_edges = 0
    for node in suffix_graph_def.node:
        data_inputs = [
            edge for edge in node.input
            if not edge.startswith("^")
        ]
        removed_control_edges += len(node.input) - len(data_inputs)
        del node.input[:]
        node.input.extend(data_inputs)

    def import_suffix_graph() -> None:
        suffix_real_input = tf.compat.v1.placeholder(
            tf.float32,
            shape=None,
            name="suffix_spectrum_real",
        )
        suffix_imag_input = tf.compat.v1.placeholder(
            tf.float32,
            shape=None,
            name="suffix_spectrum_imag",
        )

        tf.compat.v1.import_graph_def(
            suffix_graph_def,
            input_map={
                real_name: suffix_real_input,
                imag_name: suffix_imag_input,
            },
            return_elements=[audio_name],
            name="suffix",
        )

    suffix_wrapped = tf.compat.v1.wrap_function(
        import_suffix_graph,
        [],
    )
    suffix_graph = suffix_wrapped.graph

    suffix_real_tensor = suffix_graph.get_tensor_by_name(
        "suffix_spectrum_real:0"
    )
    suffix_imag_tensor = suffix_graph.get_tensor_by_name(
        "suffix_spectrum_imag:0"
    )
    suffix_audio_tensor = suffix_graph.get_tensor_by_name(
        f"suffix/{audio_name}"
    )

    suffix_fn = suffix_wrapped.prune(
        feeds=[
            suffix_real_tensor,
            suffix_imag_tensor,
        ],
        fetches=[suffix_audio_tensor],
    )

    return full_fn, cut_fn, suffix_fn, {
        "input": input_name,
        "real": real_name,
        "imag": imag_name,
        "audio": audio_name,
        "complex_node": complex_node.name,
        "irfft_node": irfft_nodes[0].name,
    }


def array_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    reference = np.asarray(reference, dtype=np.float64)
    candidate = np.asarray(candidate, dtype=np.float64)
    if reference.shape != candidate.shape:
        raise RuntimeError(
            f"Shape mismatch: {reference.shape} != {candidate.shape}"
        )

    error = candidate - reference
    ref_power = float(np.mean(reference * reference))
    error_power = float(np.mean(error * error))
    ref_rms = float(np.sqrt(ref_power))
    rmse = float(np.sqrt(error_power))
    peak = float(np.max(np.abs(reference)))
    max_abs = float(np.max(np.abs(error)))

    if error_power == 0:
        snr_db = float("inf")
    elif ref_power == 0:
        snr_db = float("-inf")
    else:
        snr_db = float(10.0 * np.log10(ref_power / error_power))

    return {
        "reference_peak": peak,
        "reference_rms": ref_rms,
        "max_abs_error": max_abs,
        "mean_abs_error": float(np.mean(np.abs(error))),
        "rmse": rmse,
        "relative_rmse": rmse / max(ref_rms, 1e-30),
        "snr_db": snr_db,
    }


def run_onnx(
    model_path: Path,
    embeddings: np.ndarray,
    optimization: str,
) -> tuple[np.ndarray, np.ndarray, float, dict[str, Any]]:
    import onnxruntime as ort

    levels = {
        "disabled": ort.GraphOptimizationLevel.ORT_DISABLE_ALL,
        "basic": ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
        "extended": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
        "all": ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
    }
    options = ort.SessionOptions()
    options.graph_optimization_level = levels[optimization]
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 2:
        raise RuntimeError(
            f"Expected 1 input and 2 outputs, got {len(inputs)} and {len(outputs)}"
        )

    started = time.perf_counter()
    real, imag = session.run(
        [outputs[0].name, outputs[1].name],
        {inputs[0].name: embeddings},
    )
    elapsed = time.perf_counter() - started

    io = {
        "input": {
            "name": inputs[0].name,
            "shape": inputs[0].shape,
            "type": inputs[0].type,
        },
        "outputs": [
            {
                "name": output.name,
                "shape": output.shape,
                "type": output.type,
            }
            for output in outputs
        ],
    }
    return real, imag, elapsed, io


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS,
    )
    parser.add_argument(
        "--sst",
        type=Path,
        default=DEFAULT_SST,
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=25,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    models_dir = args.models_dir.resolve()
    sst_path = args.sst.resolve()
    output_path = (
        args.output.resolve()
        if args.output
        else models_dir / "onnx_decoder_diagnostic.json"
    )

    onnx_path = models_dir / "spectrostream_decoder_spectrum.onnx"
    codebooks_path = models_dir / "rvq_codebooks.npy"

    if not onnx_path.is_file():
        raise FileNotFoundError(onnx_path)
    if not codebooks_path.is_file():
        raise FileNotFoundError(codebooks_path)
    if not sst_path.is_file():
        raise FileNotFoundError(sst_path)
    if args.frames <= 0:
        raise ValueError("--frames must be positive")

    print("TensorFlow:", tf.__version__)
    print("ONNX model:", onnx_path)
    print("SST:", sst_path)
    print("Frames:", args.frames)

    codebooks = np.load(codebooks_path, allow_pickle=False)
    tokens = read_first_sst_chunk(sst_path, args.frames)
    embeddings = tokens_to_embeddings(tokens, codebooks).astype(np.float32)
    actual_frames = embeddings.shape[1]

    print("Tokens:", tokens.shape, tokens.dtype)
    print("Embeddings:", embeddings.shape, embeddings.dtype)

    print("Freezing original TensorFlow decoder...")
    full_fn, cut_fn, suffix_fn, graph_info = freeze_decoder()

    embeddings_tf = tf.constant(embeddings)

    started = time.perf_counter()
    tf_audio = np.asarray(full_fn(embeddings_tf)[0], dtype=np.float32)
    tf_full_seconds = time.perf_counter() - started

    tf_real_tensor, tf_imag_tensor = cut_fn(embeddings_tf)
    tf_real = np.asarray(tf_real_tensor, dtype=np.float32)
    tf_imag = np.asarray(tf_imag_tensor, dtype=np.float32)

    # Prove that cut + suffix is exactly the original TensorFlow graph.
    tf_roundtrip = np.asarray(
        suffix_fn(tf_real_tensor, tf_imag_tensor)[0],
        dtype=np.float32,
    )
    tf_cut_roundtrip = array_metrics(tf_audio, tf_roundtrip)

    print("TF audio:", tf_audio.shape)
    print("TF spectrum:", tf_real.shape)
    print(
        "TF cut+suffix SNR:",
        f"{tf_cut_roundtrip['snr_db']:.2f} dB",
    )

    results: dict[str, Any] = {
        "frames": actual_frames,
        "duration_seconds": actual_frames / 25.0,
        "graph": graph_info,
        "tensorflow_full_seconds": tf_full_seconds,
        "tensorflow_cut_suffix": tf_cut_roundtrip,
        "runs": {},
    }

    for optimization in ("disabled", "basic", "extended", "all"):
        print(f"\nONNX optimization={optimization}")
        ort_real, ort_imag, ort_seconds, io = run_onnx(
            onnx_path,
            embeddings,
            optimization,
        )

        real_metrics = array_metrics(tf_real, ort_real)
        imag_metrics = array_metrics(tf_imag, ort_imag)

        hybrid_started = time.perf_counter()
        hybrid_audio = np.asarray(
            suffix_fn(
                tf.constant(ort_real, dtype=tf.float32),
                tf.constant(ort_imag, dtype=tf.float32),
            )[0],
            dtype=np.float32,
        )
        hybrid_seconds = time.perf_counter() - hybrid_started
        audio_metrics = array_metrics(tf_audio, hybrid_audio)

        results["runs"][optimization] = {
            "onnx_seconds": ort_seconds,
            "tensorflow_suffix_seconds": hybrid_seconds,
            "io": io,
            "spectrum_real": real_metrics,
            "spectrum_imag": imag_metrics,
            "audio": audio_metrics,
        }

        print(
            "  spectrum real: "
            f"max={real_metrics['max_abs_error']:.6g}, "
            f"SNR={real_metrics['snr_db']:.2f} dB"
        )
        print(
            "  spectrum imag: "
            f"max={imag_metrics['max_abs_error']:.6g}, "
            f"SNR={imag_metrics['snr_db']:.2f} dB"
        )
        print(
            "  final PCM:     "
            f"max={audio_metrics['max_abs_error']:.6g}, "
            f"RMSE={audio_metrics['rmse']:.6g}, "
            f"SNR={audio_metrics['snr_db']:.2f} dB"
        )

    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nDiagnostic:", output_path)

    best_name, best_run = max(
        results["runs"].items(),
        key=lambda item: item[1]["audio"]["snr_db"],
    )
    best_audio = best_run["audio"]
    print(
        f"Best optimization: {best_name}, "
        f"PCM SNR={best_audio['snr_db']:.2f} dB, "
        f"max_abs={best_audio['max_abs_error']:.6g}"
    )

    # Do not decide model acceptance from spectrum absolute error alone.
    # Exit failure only if the actual reconstructed PCM is clearly divergent.
    if not np.isfinite(best_audio["snr_db"]) or best_audio["snr_db"] < 50.0:
        print(
            "RESULT: ONNX conversion is not accurate enough yet.",
            file=sys.stderr,
        )
        return 2

    print("RESULT: ONNX conversion is numerically acceptable at PCM level.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
