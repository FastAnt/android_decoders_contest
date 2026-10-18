#!/usr/bin/env python3
"""Export a builtin-only LiteRT SpectroStream decoder core.

The original SpectroStream decoder ends with TensorFlow Complex + IRFFT ops.
Those two ops are not LiteRT builtins. This script freezes the fixed-shape
SavedModel, cuts the graph immediately before Complex, and exports a LiteRT
model that produces real/imaginary STFT bins. It also exports the exact iSTFT
window and validates a NumPy iSTFT reconstruction against the original full
TensorFlow decoder.

Expected input assets (for --frames 25):
  decoder_cpp/models/decoder_savedmodel_f25/
  decoder_cpp/models/rvq_codebooks.npy  (optional, used for realistic tests)

Outputs:
  decoder_cpp/models/decoder_core_savedmodel_f25/
  decoder_cpp/models/spectrostream_decoder_core_fp32_f25.tflite
  decoder_cpp/models/spectrostream_decoder_core_fp16_f25.tflite
  decoder_cpp/models/istft_window_f960.npy
  decoder_cpp/models/istft_window_f960.f32
  decoder_cpp/models/istft_window_f960.json
  decoder_cpp/models/decoder_core_export_f25.json

The TFLite model has:
  input:  embeddings  [1, frames, 256] float32
  output: spectrum_ri [1, 2, frames*4, 481, 2] float32

The final axis stores [real, imag]. C++ performs the 960-point IRFFT,
windowing, 480-sample overlap-add, and final crop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterable

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = BASE_DIR / "decoder_cpp/models"

SAMPLE_RATE = 48_000
CODEC_FRAME_RATE = 25
SAMPLES_PER_CODEC_FRAME = SAMPLE_RATE // CODEC_FRAME_RATE  # 1920
EMBEDDING_DIM = 256
RVQ_DEPTH = 64
CODEBOOK_SIZE = 1024
CHANNELS = 2
FFT_SIZE = 960
FREQ_BINS = FFT_SIZE // 2 + 1  # 481
HOP_SIZE = 480
STFT_FRAMES_PER_CODEC_FRAME = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cut SpectroStream before Complex/IRFFT and export a builtin-only "
            "LiteRT decoder core plus the exact iSTFT window."
        )
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIR,
    )
    parser.add_argument(
        "--saved-model-dir",
        type=Path,
        default=None,
        help=(
            "Fixed-shape full decoder SavedModel. Default: "
            "<models-dir>/decoder_savedmodel_f<frames>."
        ),
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=25,
        help="Fixed codec frames. 25 frames = 1 second.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=max(1, min(4, os.cpu_count() or 1)),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--no-fp16",
        action="store_true",
    )
    parser.add_argument(
        "--force",
        action="store_true",
    )
    return parser.parse_args()


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def normalize_shape(shape: Iterable[Any]) -> list[int | None]:
    result: list[int | None] = []
    for item in shape:
        try:
            integer = int(item)
        except (TypeError, ValueError):
            result.append(None)
            continue
        result.append(None if integer < 0 else integer)
    return result


def tensor_detail_json(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": detail.get("name"),
        "index": int(detail["index"]),
        "shape": normalize_shape(detail.get("shape", [])),
        "shape_signature": normalize_shape(detail.get("shape_signature", [])),
        "dtype": np.dtype(detail["dtype"]).name,
    }


def compare_arrays(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    if reference.shape != candidate.shape:
        raise RuntimeError(
            f"Shape mismatch: {reference.shape} != {candidate.shape}"
        )

    ref64 = reference.astype(np.float64)
    diff = ref64 - candidate.astype(np.float64)
    max_abs = float(np.max(np.abs(diff)))
    mean_abs = float(np.mean(np.abs(diff)))
    rmse = float(np.sqrt(np.mean(np.square(diff))))
    reference_rms = float(np.sqrt(np.mean(np.square(ref64))))
    snr_db = (
        float(20.0 * np.log10(reference_rms / rmse))
        if reference_rms > 0.0 and rmse > 0.0
        else float("inf")
    )
    return {
        "max_abs_error": max_abs,
        "mean_abs_error": mean_abs,
        "rmse": rmse,
        "snr_db": snr_db,
    }


def load_savedmodel_signature(
    tf: Any,
    saved_model_dir: Path,
) -> tuple[Any, Any, str, str]:
    loaded = tf.saved_model.load(str(saved_model_dir))
    if "serving_default" not in loaded.signatures:
        raise RuntimeError(
            "SavedModel has no serving_default signature: "
            f"{list(loaded.signatures)}"
        )

    signature = loaded.signatures["serving_default"]
    positional, keyword = signature.structured_input_signature
    if positional:
        raise RuntimeError(f"Expected keyword input, got positional: {positional}")
    if len(keyword) != 1:
        raise RuntimeError(f"Expected one input, got: {list(keyword)}")
    if len(signature.structured_outputs) != 1:
        raise RuntimeError(
            f"Expected one output, got: {list(signature.structured_outputs)}"
        )

    input_key = next(iter(keyword))
    output_key = next(iter(signature.structured_outputs))
    spec = keyword[input_key]
    return loaded, signature, input_key, output_key


def freeze_signature(signature: Any) -> Any:
    from tensorflow.python.framework.convert_to_constants import (  # type: ignore
        convert_variables_to_constants_v2,
    )

    try:
        return convert_variables_to_constants_v2(
            signature,
            lower_control_flow=False,
            aggressive_inlining=True,
        )
    except TypeError:
        # Compatibility with TensorFlow versions lacking aggressive_inlining.
        return convert_variables_to_constants_v2(
            signature,
            lower_control_flow=False,
        )


def find_irfft_and_complex(frozen: Any) -> tuple[Any, Any]:
    operations = frozen.graph.get_operations()
    irfft_ops = [op for op in operations if op.type in {"IRFFT", "IRFFT2D", "IRFFT3D"}]

    if len(irfft_ops) != 1:
        counts: dict[str, int] = {}
        for op in operations:
            counts[op.type] = counts.get(op.type, 0) + 1
        interesting = {
            key: value
            for key, value in sorted(counts.items())
            if "FFT" in key.upper() or "COMPLEX" in key.upper()
        }
        raise RuntimeError(
            f"Expected exactly one IRFFT op, found {len(irfft_ops)}. "
            f"FFT-related ops: {interesting}"
        )

    irfft_op = irfft_ops[0]
    if not irfft_op.inputs:
        raise RuntimeError("IRFFT op has no input")

    complex_op = irfft_op.inputs[0].op
    if complex_op.type != "Complex" or len(complex_op.inputs) != 2:
        raise RuntimeError(
            "Expected IRFFT input to be Complex(real, imag), got "
            f"{complex_op.type} with {len(complex_op.inputs)} inputs"
        )

    return irfft_op, complex_op


def static_tensor_value(tf: Any, tensor: Any) -> np.ndarray | None:
    value = tf.get_static_value(tensor)
    if value is not None:
        return np.asarray(value)

    op = tensor.op
    if op.type == "Const":
        try:
            return np.asarray(tf.make_ndarray(op.get_attr("value")))
        except Exception:
            return None

    if op.type in {"Identity", "StopGradient"} and op.inputs:
        return static_tensor_value(tf, op.inputs[0])

    return None


def find_window_tensor(tf: Any, irfft_op: Any, fft_size: int) -> tuple[Any, np.ndarray]:
    """Find the constant window multiplied with IRFFT output."""

    queue: deque[tuple[Any, int]] = deque([(irfft_op.outputs[0], 0)])
    visited: set[str] = set()
    passthrough_types = {"Identity", "Cast", "Reshape", "Squeeze", "ExpandDims"}

    while queue:
        tensor, depth = queue.popleft()
        if tensor.name in visited or depth > 5:
            continue
        visited.add(tensor.name)

        for consumer in tensor.consumers():
            if consumer.type in {"Mul", "MulNoNan"} and len(consumer.inputs) == 2:
                for candidate in consumer.inputs:
                    if candidate is tensor:
                        continue
                    value = static_tensor_value(tf, candidate)
                    if value is None:
                        continue
                    flattened = np.asarray(value, dtype=np.float32).reshape(-1)
                    if flattened.size == fft_size and np.isfinite(flattened).all():
                        return candidate, flattened

            if consumer.type in passthrough_types:
                for output in consumer.outputs:
                    queue.append((output, depth + 1))

    raise RuntimeError(
        f"Could not find a constant window of length {fft_size} downstream of IRFFT"
    )


def create_pruned_core_function(
    tf: Any,
    frozen: Any,
    real_tensor: Any,
    imag_tensor: Any,
) -> Any:
    """Create a callable frozen function ending before Complex/IRFFT."""

    if len(frozen.inputs) != 1:
        raise RuntimeError(
            f"Expected one frozen input, got {[tensor.name for tensor in frozen.inputs]}"
        )

    graph_def = frozen.graph.as_graph_def(add_shapes=True)
    destination_nodes = [real_tensor.op.name, imag_tensor.op.name]
    pruned_graph_def = tf.compat.v1.graph_util.extract_sub_graph(
        graph_def,
        destination_nodes,
    )

    def import_graph() -> None:
        tf.compat.v1.import_graph_def(pruned_graph_def, name="")

    wrapped = tf.compat.v1.wrap_function(import_graph, [])
    graph = wrapped.graph

    input_tensor = graph.get_tensor_by_name(frozen.inputs[0].name)
    real_imported = graph.get_tensor_by_name(real_tensor.name)
    imag_imported = graph.get_tensor_by_name(imag_tensor.name)

    return wrapped.prune(
        feeds=[input_tensor],
        fetches=[real_imported, imag_imported],
    )


def export_core_savedmodel(
    tf: Any,
    pruned_core: Any,
    frames: int,
    destination: Path,
    force: bool,
) -> tuple[Any, Any]:
    class DecoderCore(tf.Module):
        def __init__(self) -> None:
            super().__init__(name=f"spectrostream_decoder_core_f{frames}")
            self.core = pruned_core

        @tf.function(
            input_signature=[
                tf.TensorSpec(
                    [1, frames, EMBEDDING_DIM],
                    tf.float32,
                    name="embeddings",
                )
            ],
            autograph=False,
        )
        def infer(self, embeddings: Any) -> dict[str, Any]:
            real, imag = self.core(embeddings)
            spectrum_ri = tf.stack(
                [tf.cast(real, tf.float32), tf.cast(imag, tf.float32)],
                axis=-1,
                name="spectrum_ri",
            )
            return {"spectrum_ri": spectrum_ri}

    module = DecoderCore()
    concrete = module.infer.get_concrete_function()

    probe = module.infer(
        tf.zeros([1, frames, EMBEDDING_DIM], dtype=tf.float32)
    )["spectrum_ri"]
    expected = (
        1,
        CHANNELS,
        frames * STFT_FRAMES_PER_CODEC_FRAME,
        FREQ_BINS,
        2,
    )
    if tuple(probe.shape) != expected:
        raise RuntimeError(
            f"Unexpected decoder core output: {tuple(probe.shape)}; expected {expected}"
        )

    if destination.exists():
        if not force:
            raise FileExistsError(
                f"{destination} exists; pass --force to replace it"
            )
        shutil.rmtree(destination)

    tf.saved_model.save(
        module,
        str(destination),
        signatures={"serving_default": concrete},
    )
    return module, concrete


def build_test_embeddings(models_dir: Path, frames: int) -> tuple[np.ndarray, str]:
    rng = np.random.default_rng(20260711)
    codebooks_path = models_dir / "rvq_codebooks.npy"

    if codebooks_path.is_file():
        codebooks = np.load(codebooks_path, allow_pickle=False, mmap_mode="r")
        expected = (RVQ_DEPTH, CODEBOOK_SIZE, EMBEDDING_DIM)
        if tuple(codebooks.shape) != expected:
            raise RuntimeError(
                f"Unexpected codebooks shape: {codebooks.shape}; expected {expected}"
            )

        tokens = rng.integers(
            0,
            CODEBOOK_SIZE,
            size=(frames, RVQ_DEPTH),
            dtype=np.int32,
        )
        embeddings = np.zeros((frames, EMBEDDING_DIM), dtype=np.float32)
        for depth in range(RVQ_DEPTH):
            embeddings += np.asarray(
                codebooks[depth, tokens[:, depth], :],
                dtype=np.float32,
            )
        return embeddings[None, ...], "rvq_codebooks"

    return (
        rng.normal(0.0, 0.1, size=(1, frames, EMBEDDING_DIM)).astype(np.float32),
        "deterministic_normal",
    )


def run_savedmodel(
    model: Any,
    input_key: str,
    output_key: str,
    embeddings: np.ndarray,
) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    output = model.signatures["serving_default"](
        **{input_key: embeddings}
    )[output_key]
    seconds = time.perf_counter() - started
    return np.asarray(output.numpy(), dtype=np.float32), seconds


def numpy_istft(
    spectrum_ri: np.ndarray,
    window: np.ndarray,
    target_samples: int,
    fft_size: int = FFT_SIZE,
    hop_size: int = HOP_SIZE,
) -> np.ndarray:
    """Reproduce TensorFlow IRFFT + window + overlap-add in NumPy."""

    expected_rank = 5
    if spectrum_ri.ndim != expected_rank or spectrum_ri.shape[-1] != 2:
        raise ValueError(
            f"Expected spectrum [B,C,T,F,2], got {spectrum_ri.shape}"
        )
    if spectrum_ri.shape[-2] != fft_size // 2 + 1:
        raise ValueError(
            f"Expected {fft_size // 2 + 1} frequency bins, got {spectrum_ri.shape[-2]}"
        )

    real = spectrum_ri[..., 0].astype(np.float32)
    imag = spectrum_ri[..., 1].astype(np.float32)
    spectrum = real.astype(np.complex64) + 1j * imag.astype(np.complex64)

    frames = np.fft.irfft(spectrum, n=fft_size, axis=-1).astype(np.float32)
    window32 = np.asarray(window, dtype=np.float32).reshape(1, 1, 1, fft_size)
    frames *= window32

    batch, channels, frame_count, _ = frames.shape
    full_samples = (frame_count - 1) * hop_size + fft_size
    pcm = np.zeros((batch, channels, full_samples), dtype=np.float32)

    for frame_index in range(frame_count):
        start = frame_index * hop_size
        pcm[:, :, start : start + fft_size] += frames[:, :, frame_index, :]

    if target_samples > full_samples:
        raise RuntimeError(
            f"Requested {target_samples} samples, but iSTFT produced {full_samples}"
        )

    return np.transpose(pcm[:, :, :target_samples], (0, 2, 1)).copy()


def export_window(
    output_dir: Path,
    window: np.ndarray,
    fft_size: int,
    hop_size: int,
) -> dict[str, Any]:
    window = np.ascontiguousarray(np.asarray(window, dtype="<f4").reshape(-1))
    if window.size != fft_size:
        raise RuntimeError(f"Window length {window.size} != FFT size {fft_size}")

    npy_path = output_dir / f"istft_window_f{fft_size}.npy"
    raw_path = output_dir / f"istft_window_f{fft_size}.f32"
    json_path = output_dir / f"istft_window_f{fft_size}.json"

    np.save(npy_path, window, allow_pickle=False)
    window.tofile(raw_path)

    metadata = {
        "format": "spectrostream_istft_window_v1",
        "fft_size": fft_size,
        "frequency_bins": fft_size // 2 + 1,
        "hop_size": hop_size,
        "dtype": "float32",
        "endianness": "little",
        "layout": "contiguous [fft_size]",
        "raw_bytes": raw_path.stat().st_size,
        "raw_sha256": sha256_file(raw_path),
        "npy_sha256": sha256_file(npy_path),
        "min": float(window.min()),
        "max": float(window.max()),
        "sum": float(window.sum()),
        "sum_squares": float(np.sum(np.square(window.astype(np.float64)))),
    }
    atomic_write_json(json_path, metadata)
    return metadata


def convert_tflite(
    tf: Any,
    saved_model_dir: Path,
    destination: Path,
    precision: str,
    force: bool,
) -> dict[str, Any]:
    if destination.exists() and not force:
        raise FileExistsError(
            f"{destination} exists; pass --force to replace it"
        )

    converter = tf.lite.TFLiteConverter.from_saved_model(str(saved_model_dir))
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    converter.inference_input_type = tf.float32
    converter.inference_output_type = tf.float32

    if precision == "fp16":
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.target_spec.supported_types = [tf.float16]
    elif precision != "fp32":
        raise ValueError(f"Unsupported precision: {precision}")

    started = time.perf_counter()
    content = converter.convert()
    conversion_seconds = time.perf_counter() - started
    atomic_write_bytes(destination, content)

    return {
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "precision": precision,
        "operator_mode": "builtin_only",
        "conversion_seconds": conversion_seconds,
    }


def get_interpreter_class(tf: Any) -> tuple[Any, str]:
    try:
        from ai_edge_litert.interpreter import Interpreter  # type: ignore

        return Interpreter, "ai_edge_litert"
    except ImportError:
        return tf.lite.Interpreter, "tensorflow.lite"


def inspect_operators(interpreter: Any) -> dict[str, Any]:
    if not hasattr(interpreter, "_get_ops_details"):
        return {
            "names": [],
            "flex_operators": [],
            "inspection_available": False,
        }

    details = interpreter._get_ops_details()  # pylint: disable=protected-access
    names = [str(item.get("op_name", "")) for item in details]
    flex = sorted({name for name in names if name.startswith("Flex")})
    return {
        "names": names,
        "unique_names": sorted(set(names)),
        "flex_operators": flex,
        "inspection_available": True,
    }


def run_tflite(
    tf: Any,
    model_path: Path,
    embeddings: np.ndarray,
    threads: int,
    runs: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    Interpreter, runtime_name = get_interpreter_class(tf)
    interpreter = Interpreter(model_path=str(model_path), num_threads=threads)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    if len(input_details) != 1 or len(output_details) != 1:
        raise RuntimeError(
            f"Expected one TFLite input/output, got "
            f"{len(input_details)}/{len(output_details)}"
        )

    if tuple(input_details[0]["shape"]) != tuple(embeddings.shape):
        raise RuntimeError(
            f"Unexpected TFLite input shape {input_details[0]['shape']}; "
            f"expected {embeddings.shape}"
        )

    input_index = int(input_details[0]["index"])
    output_index = int(output_details[0]["index"])

    interpreter.set_tensor(input_index, embeddings)
    interpreter.invoke()
    interpreter.set_tensor(input_index, embeddings)
    interpreter.invoke()

    timings: list[float] = []
    output: np.ndarray | None = None
    for _ in range(runs):
        interpreter.set_tensor(input_index, embeddings)
        started = time.perf_counter()
        interpreter.invoke()
        timings.append(time.perf_counter() - started)
        output = np.asarray(interpreter.get_tensor(output_index), dtype=np.float32)

    assert output is not None
    operators = inspect_operators(interpreter)
    if operators["flex_operators"]:
        raise RuntimeError(
            f"Core model unexpectedly contains Flex ops: {operators['flex_operators']}"
        )

    metadata = {
        "runtime": runtime_name,
        "threads": threads,
        "input": tensor_detail_json(input_details[0]),
        "output": tensor_detail_json(output_details[0]),
        "inference_seconds": {
            "runs": runs,
            "min": float(np.min(timings)),
            "median": float(np.median(timings)),
            "mean": float(np.mean(timings)),
            "max": float(np.max(timings)),
        },
        "operators": operators,
    }
    return output, metadata


def main() -> int:
    args = parse_args()
    if args.frames <= 0:
        raise ValueError("--frames must be positive")
    if args.threads <= 0:
        raise ValueError("--threads must be positive")
    if args.runs <= 0:
        raise ValueError("--runs must be positive")

    # Must be set before importing TensorFlow.
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "1")

    import tensorflow as tf

    models_dir = args.models_dir.resolve()
    full_saved_model_dir = (
        args.saved_model_dir.resolve()
        if args.saved_model_dir is not None
        else models_dir / f"decoder_savedmodel_f{args.frames}"
    )
    if not full_saved_model_dir.is_dir():
        raise FileNotFoundError(
            f"Fixed full decoder SavedModel not found: {full_saved_model_dir}"
        )
    models_dir.mkdir(parents=True, exist_ok=True)

    target_samples = args.frames * SAMPLES_PER_CODEC_FRAME
    expected_stft_frames = args.frames * STFT_FRAMES_PER_CODEC_FRAME

    print("TensorFlow:", tf.__version__)
    print("Full fixed SavedModel:", full_saved_model_dir)
    print("Models directory:", models_dir)
    print(
        f"Window: {args.frames} codec frames = "
        f"{args.frames / CODEC_FRAME_RATE:.3f}s = {target_samples} PCM samples"
    )

    full_model, full_signature, full_input_key, full_output_key = (
        load_savedmodel_signature(tf, full_saved_model_dir)
    )
    print("Full input key:", full_input_key)
    print("Full output key:", full_output_key)

    print("Freezing and inlining TensorFlow graph...")
    freeze_started = time.perf_counter()
    frozen = freeze_signature(full_signature)
    print(f"Frozen in {time.perf_counter() - freeze_started:.2f}s")

    irfft_op, complex_op = find_irfft_and_complex(frozen)
    real_tensor, imag_tensor = complex_op.inputs
    print("Complex op:", complex_op.name)
    print("IRFFT op:", irfft_op.name)
    print("Real tensor:", real_tensor.name, real_tensor.shape)
    print("Imag tensor:", imag_tensor.name, imag_tensor.shape)

    expected_spectrum_shape = (
        1,
        CHANNELS,
        expected_stft_frames,
        FREQ_BINS,
    )
    if tuple(real_tensor.shape) != expected_spectrum_shape:
        raise RuntimeError(
            f"Unexpected real spectrum shape {tuple(real_tensor.shape)}; "
            f"expected {expected_spectrum_shape}"
        )
    if tuple(imag_tensor.shape) != expected_spectrum_shape:
        raise RuntimeError(
            f"Unexpected imag spectrum shape {tuple(imag_tensor.shape)}; "
            f"expected {expected_spectrum_shape}"
        )

    _, window = find_window_tensor(tf, irfft_op, FFT_SIZE)
    window_metadata = export_window(
        output_dir=models_dir,
        window=window,
        fft_size=FFT_SIZE,
        hop_size=HOP_SIZE,
    )
    print(
        f"Exported iSTFT window: {window.size} float32 values, "
        f"SHA256={window_metadata['raw_sha256']}"
    )

    pruned_core = create_pruned_core_function(
        tf=tf,
        frozen=frozen,
        real_tensor=real_tensor,
        imag_tensor=imag_tensor,
    )

    core_saved_model_dir = models_dir / f"decoder_core_savedmodel_f{args.frames}"
    print("Exporting core SavedModel:", core_saved_model_dir)
    export_core_savedmodel(
        tf=tf,
        pruned_core=pruned_core,
        frames=args.frames,
        destination=core_saved_model_dir,
        force=args.force,
    )

    core_model, _, core_input_key, core_output_key = load_savedmodel_signature(
        tf,
        core_saved_model_dir,
    )
    embeddings, embedding_source = build_test_embeddings(models_dir, args.frames)

    full_audio, full_tf_seconds = run_savedmodel(
        model=full_model,
        input_key=full_input_key,
        output_key=full_output_key,
        embeddings=embeddings,
    )
    core_tf, core_tf_seconds = run_savedmodel(
        model=core_model,
        input_key=core_input_key,
        output_key=core_output_key,
        embeddings=embeddings,
    )
    reconstructed_tf_core = numpy_istft(
        spectrum_ri=core_tf,
        window=window,
        target_samples=target_samples,
    )
    tf_core_audio_comparison = compare_arrays(full_audio, reconstructed_tf_core)

    print("Validation embeddings:", embedding_source)
    print("Full TensorFlow audio:", full_audio.shape)
    print("TensorFlow core spectrum:", core_tf.shape)
    print(
        "TF core + NumPy iSTFT vs full TF: "
        f"max_abs={tf_core_audio_comparison['max_abs_error']:.3e}, "
        f"RMSE={tf_core_audio_comparison['rmse']:.3e}, "
        f"SNR={tf_core_audio_comparison['snr_db']:.2f} dB"
    )

    if (
        tf_core_audio_comparison["max_abs_error"] > 1e-3
        or tf_core_audio_comparison["rmse"] > 1e-4
    ):
        raise RuntimeError(
            "Exported window/NumPy iSTFT does not reproduce the full decoder: "
            f"{tf_core_audio_comparison}"
        )

    report: dict[str, Any] = {
        "format": "spectrostream_litert_core_export_v1",
        "tensorflow_version": tf.__version__,
        "full_saved_model": str(full_saved_model_dir),
        "core_saved_model": str(core_saved_model_dir),
        "frames": args.frames,
        "duration_seconds": args.frames / CODEC_FRAME_RATE,
        "embedding_dim": EMBEDDING_DIM,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "codec_frame_rate": CODEC_FRAME_RATE,
        "samples_per_codec_frame": SAMPLES_PER_CODEC_FRAME,
        "stft": {
            "fft_size": FFT_SIZE,
            "frequency_bins": FREQ_BINS,
            "hop_size": HOP_SIZE,
            "stft_frames": expected_stft_frames,
            "target_samples": target_samples,
            "full_ola_samples": (expected_stft_frames - 1) * HOP_SIZE + FFT_SIZE,
            "final_crop_samples": (
                (expected_stft_frames - 1) * HOP_SIZE
                + FFT_SIZE
                - target_samples
            ),
            "window": window_metadata,
        },
        "io": {
            "input_name": "embeddings",
            "input_shape": [1, args.frames, EMBEDDING_DIM],
            "output_name": "spectrum_ri",
            "output_shape": [
                1,
                CHANNELS,
                expected_stft_frames,
                FREQ_BINS,
                2,
            ],
            "output_last_axis": ["real", "imag"],
        },
        "test_embedding_source": embedding_source,
        "tensorflow_seconds": {
            "full_decoder": full_tf_seconds,
            "core_decoder": core_tf_seconds,
        },
        "tensorflow_core_plus_numpy_istft_vs_full": tf_core_audio_comparison,
        "models": {},
    }

    precisions = ["fp32"] + ([] if args.no_fp16 else ["fp16"])
    for precision in precisions:
        model_path = models_dir / (
            f"spectrostream_decoder_core_{precision}_f{args.frames}.tflite"
        )
        print(f"\nConverting {precision.upper()} builtin-only LiteRT model...")
        conversion = convert_tflite(
            tf=tf,
            saved_model_dir=core_saved_model_dir,
            destination=model_path,
            precision=precision,
            force=args.force,
        )

        tflite_core, runtime_metadata = run_tflite(
            tf=tf,
            model_path=model_path,
            embeddings=embeddings,
            threads=args.threads,
            runs=args.runs,
        )
        core_comparison = compare_arrays(core_tf, tflite_core)
        tflite_audio = numpy_istft(
            spectrum_ri=tflite_core,
            window=window,
            target_samples=target_samples,
        )
        audio_comparison = compare_arrays(full_audio, tflite_audio)

        runtime_metadata["core_vs_tensorflow_core"] = core_comparison
        runtime_metadata["audio_vs_full_tensorflow"] = audio_comparison
        conversion["validation"] = runtime_metadata
        report["models"][precision] = conversion

        median = runtime_metadata["inference_seconds"]["median"]
        print(
            f"{precision.upper()} OK: "
            f"{model_path.stat().st_size / 1024**2:.2f} MiB, "
            f"median={median:.4f}s, "
            f"core RMSE={core_comparison['rmse']:.3e}, "
            f"audio RMSE={audio_comparison['rmse']:.3e}, "
            f"audio SNR={audio_comparison['snr_db']:.2f} dB"
        )

        if precision == "fp32":
            if (
                core_comparison["max_abs_error"] > 1e-3
                or core_comparison["rmse"] > 1e-4
                or audio_comparison["max_abs_error"] > 2e-3
                or audio_comparison["rmse"] > 2e-4
            ):
                raise RuntimeError(
                    "FP32 LiteRT core validation failed: "
                    f"core={core_comparison}, audio={audio_comparison}"
                )

    report_path = models_dir / f"decoder_core_export_f{args.frames}.json"
    atomic_write_json(report_path, report)

    print("\nDecoder core export complete")
    print("Core SavedModel:", core_saved_model_dir)
    print("Report:", report_path)
    print(
        "C++ DSP parameters: "
        f"IRFFT={FFT_SIZE}, hop={HOP_SIZE}, "
        f"window=istft_window_f{FFT_SIZE}.f32, crop={report['stft']['final_crop_samples']}"
    )
    for precision, model in report["models"].items():
        print(
            f"  {precision}: {model['path']} "
            f"({model['bytes'] / 1024**2:.2f} MiB)"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
