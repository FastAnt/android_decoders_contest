#!/usr/bin/env python3
"""Export and validate SpectroStream decoder models for LiteRT/TFLite.

Input expected from the previous decoder export stage:
  decoder_cpp/models/decoder_savedmodel/
  decoder_cpp/models/rvq_codebooks.npy   (optional, improves test inputs)

Outputs (for --frames 25):
  decoder_savedmodel_f25/
  spectrostream_decoder_fp32_f25_builtin.tflite
  spectrostream_decoder_fp16_f25_builtin.tflite
  or *_flex.tflite when SELECT_TF_OPS is required
  litert_export_f25.json

The .tflite FlatBuffer is the model format used by LiteRT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = BASE_DIR / "decoder_cpp/models"
SAMPLE_RATE = 48_000
FRAME_RATE = 25
SAMPLES_PER_FRAME = SAMPLE_RATE // FRAME_RATE
EMBEDDING_DIM = 256
RVQ_DEPTH = 64
CODEBOOK_SIZE = 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export fixed-shape SpectroStream decoder models to LiteRT/TFLite "
            "and validate them against TensorFlow."
        )
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIR,
        help="Directory containing decoder_savedmodel and exported codebooks.",
    )
    parser.add_argument(
        "--saved-model-dir",
        type=Path,
        default=None,
        help="Override source SavedModel path.",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=25,
        help="Fixed codec frames per inference. 25 frames = 1 second.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Measured LiteRT CPU inference runs after warm-up.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=max(1, min(4, os.cpu_count() or 1)),
        help="CPU threads used by the Python LiteRT/TFLite Interpreter.",
    )
    parser.add_argument(
        "--no-fp16",
        action="store_true",
        help="Export only FP32.",
    )
    parser.add_argument(
        "--no-flex-fallback",
        action="store_true",
        help="Fail instead of retrying with SELECT_TF_OPS.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing fixed SavedModel and .tflite files.",
    )
    return parser.parse_args()


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def normalize_shape(shape: Any) -> list[int | None]:
    result: list[int | None] = []
    for value in shape:
        try:
            integer = int(value)
        except (TypeError, ValueError):
            result.append(None)
            continue
        result.append(None if integer < 0 else integer)
    return result


def scalar_json(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def tensor_detail_json(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": detail.get("name"),
        "index": int(detail["index"]),
        "shape": normalize_shape(detail.get("shape", [])),
        "shape_signature": normalize_shape(detail.get("shape_signature", [])),
        "dtype": np.dtype(detail["dtype"]).name,
        "quantization": [scalar_json(x) for x in detail.get("quantization", ())],
    }


def get_interpreter_class(tf: Any) -> tuple[Any, str]:
    """Prefer the standalone LiteRT Python runtime, then TensorFlow fallback."""
    try:
        from ai_edge_litert.interpreter import Interpreter  # type: ignore

        return Interpreter, "ai_edge_litert"
    except ImportError:
        return tf.lite.Interpreter, "tensorflow.lite"


def load_signature(tf: Any, saved_model_dir: Path) -> tuple[Any, str, str]:
    loaded = tf.saved_model.load(str(saved_model_dir))
    signatures = loaded.signatures
    if "serving_default" not in signatures:
        raise RuntimeError(
            f"SavedModel has no serving_default signature: {list(signatures)}"
        )

    signature = signatures["serving_default"]
    positional, keyword = signature.structured_input_signature
    if positional:
        raise RuntimeError(
            "Expected keyword-only SavedModel input, got positional inputs: "
            f"{positional}"
        )
    if len(keyword) != 1:
        raise RuntimeError(
            f"Expected one SavedModel input, got: {list(keyword)}"
        )
    if len(signature.structured_outputs) != 1:
        raise RuntimeError(
            "Expected one SavedModel output, got: "
            f"{list(signature.structured_outputs)}"
        )

    input_key = next(iter(keyword))
    output_key = next(iter(signature.structured_outputs))
    input_spec = keyword[input_key]

    if input_spec.dtype != tf.float32:
        raise RuntimeError(f"Expected float32 input, got {input_spec.dtype}")
    if input_spec.shape.rank != 3:
        raise RuntimeError(f"Expected rank-3 embeddings, got {input_spec.shape}")
    if input_spec.shape[-1] not in (None, EMBEDDING_DIM):
        raise RuntimeError(
            f"Expected embedding dimension {EMBEDDING_DIM}, got {input_spec.shape}"
        )

    return loaded, input_key, output_key


def export_fixed_savedmodel(
    tf: Any,
    source_model: Any,
    input_key: str,
    output_key: str,
    frames: int,
    destination: Path,
    force: bool,
) -> tuple[Any, Any]:
    """Wrap a dynamic SavedModel with a fixed [1, frames, 256] signature."""

    class FixedDecoder(tf.Module):
        def __init__(self, model: Any) -> None:
            super().__init__(name=f"spectrostream_decoder_f{frames}")
            self.model = model

        @tf.function(
            input_signature=[
                tf.TensorSpec(
                    shape=[1, frames, EMBEDDING_DIM],
                    dtype=tf.float32,
                    name="embeddings",
                )
            ],
            autograph=False,
        )
        def decode(self, embeddings: Any) -> dict[str, Any]:
            output = self.model.signatures["serving_default"](
                **{input_key: embeddings}
            )[output_key]
            return {"audio": tf.cast(output, tf.float32)}

    wrapper = FixedDecoder(source_model)
    concrete = wrapper.decode.get_concrete_function()

    test_input = tf.zeros([1, frames, EMBEDDING_DIM], tf.float32)
    test_output = wrapper.decode(test_input)["audio"]
    expected_shape = (1, frames * SAMPLES_PER_FRAME, 2)
    if tuple(test_output.shape) != expected_shape:
        raise RuntimeError(
            f"Unexpected fixed decoder output: {tuple(test_output.shape)}; "
            f"expected {expected_shape}"
        )

    if destination.exists():
        if not force:
            raise FileExistsError(
                f"{destination} already exists; pass --force to replace it"
            )
        shutil.rmtree(destination)

    tf.saved_model.save(
        wrapper,
        str(destination),
        signatures={"serving_default": concrete},
    )
    return wrapper, concrete


def convert_model(
    tf: Any,
    fixed_saved_model: Path,
    destination: Path,
    precision: str,
    use_flex: bool,
    force: bool,
) -> dict[str, Any]:
    if destination.exists() and not force:
        raise FileExistsError(
            f"{destination} already exists; pass --force to replace it"
        )

    converter = tf.lite.TFLiteConverter.from_saved_model(str(fixed_saved_model))
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    if use_flex:
        converter.target_spec.supported_ops.append(
            tf.lite.OpsSet.SELECT_TF_OPS
        )

    if precision == "fp16":
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.target_spec.supported_types = [tf.float16]
    elif precision != "fp32":
        raise ValueError(f"Unsupported precision: {precision}")

    # Keep float32 I/O. FP16 conversion compresses eligible constant weights.
    converter.inference_input_type = tf.float32
    converter.inference_output_type = tf.float32

    started = time.perf_counter()
    model_content = converter.convert()
    seconds = time.perf_counter() - started
    atomic_write(destination, model_content)

    return {
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "precision": precision,
        "operator_mode": "flex" if use_flex else "builtin",
        "conversion_seconds": seconds,
    }


def build_test_embeddings(models_dir: Path, frames: int) -> tuple[np.ndarray, str]:
    """Generate deterministic, codec-shaped embeddings for validation."""
    codebooks_path = models_dir / "rvq_codebooks.npy"
    rng = np.random.default_rng(20260711)

    if codebooks_path.is_file():
        codebooks = np.load(codebooks_path, allow_pickle=False, mmap_mode="r")
        expected_shape = (RVQ_DEPTH, CODEBOOK_SIZE, EMBEDDING_DIM)
        if tuple(codebooks.shape) != expected_shape:
            raise RuntimeError(
                f"Unexpected codebook shape {codebooks.shape}; "
                f"expected {expected_shape}"
            )
        tokens = rng.integers(
            0,
            CODEBOOK_SIZE,
            size=(frames, RVQ_DEPTH),
            dtype=np.int32,
        )
        embeddings = np.zeros((frames, EMBEDDING_DIM), dtype=np.float32)
        for layer in range(RVQ_DEPTH):
            embeddings += np.asarray(
                codebooks[layer, tokens[:, layer], :],
                dtype=np.float32,
            )
        return embeddings[None, ...], "rvq_codebooks"

    embeddings = rng.normal(
        0.0,
        0.1,
        size=(1, frames, EMBEDDING_DIM),
    ).astype(np.float32)
    return embeddings, "normal_random_fallback"


def run_tensorflow_reference(
    tf: Any,
    fixed_saved_model: Path,
    embeddings: np.ndarray,
) -> tuple[np.ndarray, float]:
    model = tf.saved_model.load(str(fixed_saved_model))
    signature = model.signatures["serving_default"]
    input_key = next(iter(signature.structured_input_signature[1]))
    output_key = next(iter(signature.structured_outputs))

    started = time.perf_counter()
    output = signature(**{input_key: tf.constant(embeddings)})[output_key]
    seconds = time.perf_counter() - started
    return np.asarray(output.numpy(), dtype=np.float32), seconds


def inspect_ops(interpreter: Any) -> dict[str, Any]:
    try:
        details = interpreter._get_ops_details()  # pylint: disable=protected-access
    except (AttributeError, RuntimeError):
        return {
            "available": False,
            "operator_count": None,
            "operators": [],
            "flex_operators": [],
        }

    names = [str(item.get("op_name", "UNKNOWN")) for item in details]
    unique_names = sorted(set(names))
    flex = sorted(name for name in unique_names if name.startswith("Flex"))
    return {
        "available": True,
        "operator_count": len(names),
        "operators": unique_names,
        "flex_operators": flex,
    }


def compare_outputs(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    if reference.shape != candidate.shape:
        raise RuntimeError(
            f"Output shape mismatch: {reference.shape} != {candidate.shape}"
        )

    reference64 = reference.astype(np.float64)
    difference = reference64 - candidate.astype(np.float64)
    max_abs = float(np.max(np.abs(difference)))
    mean_abs = float(np.mean(np.abs(difference)))
    rmse = float(np.sqrt(np.mean(np.square(difference))))
    reference_rms = float(np.sqrt(np.mean(np.square(reference64))))
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


def validate_tflite(
    tf: Any,
    model_path: Path,
    embeddings: np.ndarray,
    reference: np.ndarray,
    threads: int,
    runs: int,
) -> dict[str, Any]:
    Interpreter, runtime_name = get_interpreter_class(tf)
    interpreter = Interpreter(model_path=str(model_path), num_threads=threads)

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    if len(input_details) != 1 or len(output_details) != 1:
        raise RuntimeError(
            f"Expected one input/output, got {len(input_details)}/"
            f"{len(output_details)}"
        )

    wanted_shape = np.asarray(embeddings.shape, dtype=np.int32)
    if not np.array_equal(input_details[0]["shape"], wanted_shape):
        interpreter.resize_tensor_input(
            input_details[0]["index"],
            wanted_shape,
            strict=False,
        )

    allocation_started = time.perf_counter()
    interpreter.allocate_tensors()
    allocation_seconds = time.perf_counter() - allocation_started

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    interpreter.set_tensor(input_details[0]["index"], embeddings)

    # Warm-up includes possible lazy kernel initialization.
    interpreter.invoke()
    interpreter.set_tensor(input_details[0]["index"], embeddings)
    interpreter.invoke()

    measured: list[float] = []
    candidate: np.ndarray | None = None
    for _ in range(runs):
        interpreter.set_tensor(input_details[0]["index"], embeddings)
        started = time.perf_counter()
        interpreter.invoke()
        measured.append(time.perf_counter() - started)
        candidate = np.asarray(
            interpreter.get_tensor(output_details[0]["index"]),
            dtype=np.float32,
        )

    assert candidate is not None
    metrics = compare_outputs(reference, candidate)
    ops = inspect_ops(interpreter)

    return {
        "runtime": runtime_name,
        "threads": threads,
        "allocation_seconds": allocation_seconds,
        "inference_seconds": {
            "runs": runs,
            "min": float(np.min(measured)),
            "median": float(np.median(measured)),
            "mean": float(np.mean(measured)),
            "max": float(np.max(measured)),
        },
        "input": tensor_detail_json(input_details[0]),
        "output": tensor_detail_json(output_details[0]),
        "operators": ops,
        "comparison": metrics,
    }


def attempt_conversion(
    tf: Any,
    fixed_saved_model: Path,
    models_dir: Path,
    frames: int,
    precision: str,
    allow_flex_fallback: bool,
    force: bool,
) -> tuple[dict[str, Any], Path]:
    errors: list[dict[str, str]] = []
    modes = [False] + ([True] if allow_flex_fallback else [])

    for use_flex in modes:
        mode = "flex" if use_flex else "builtin"
        destination = models_dir / (
            f"spectrostream_decoder_{precision}_f{frames}_{mode}.tflite"
        )
        try:
            result = convert_model(
                tf=tf,
                fixed_saved_model=fixed_saved_model,
                destination=destination,
                precision=precision,
                use_flex=use_flex,
                force=force,
            )
            result["attempt_errors"] = errors
            return result, destination
        except Exception as error:  # conversion errors vary by TF version
            errors.append({
                "operator_mode": mode,
                "error_type": type(error).__name__,
                "error": str(error),
            })
            print(
                f"{precision.upper()} {mode} conversion failed: "
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
            )

    raise RuntimeError(
        f"All {precision} LiteRT conversion attempts failed: "
        f"{json.dumps(errors, ensure_ascii=False)}"
    )


def main() -> int:
    args = parse_args()
    if args.frames <= 0:
        raise ValueError("--frames must be positive")
    if args.runs <= 0:
        raise ValueError("--runs must be positive")
    if args.threads <= 0:
        raise ValueError("--threads must be positive")

    # Export is intentionally CPU-only and should not reserve GPU memory.
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "1")

    import tensorflow as tf

    models_dir = args.models_dir.resolve()
    saved_model_dir = (
        args.saved_model_dir.resolve()
        if args.saved_model_dir is not None
        else models_dir / "decoder_savedmodel"
    )
    if not saved_model_dir.is_dir():
        raise FileNotFoundError(
            f"Source SavedModel not found: {saved_model_dir}"
        )
    models_dir.mkdir(parents=True, exist_ok=True)

    print("TensorFlow:", tf.__version__)
    print("Source SavedModel:", saved_model_dir)
    print("Models directory:", models_dir)
    print(
        f"Fixed window: {args.frames} frames = "
        f"{args.frames / FRAME_RATE:.3f}s = "
        f"{args.frames * SAMPLES_PER_FRAME} PCM samples"
    )

    source_model, input_key, output_key = load_signature(
        tf,
        saved_model_dir,
    )
    print("Source input key:", input_key)
    print("Source output key:", output_key)

    fixed_saved_model = models_dir / f"decoder_savedmodel_f{args.frames}"
    started = time.perf_counter()
    export_fixed_savedmodel(
        tf=tf,
        source_model=source_model,
        input_key=input_key,
        output_key=output_key,
        frames=args.frames,
        destination=fixed_saved_model,
        force=args.force,
    )
    print(
        f"Fixed SavedModel exported in {time.perf_counter() - started:.2f}s: "
        f"{fixed_saved_model}"
    )

    embeddings, embedding_source = build_test_embeddings(
        models_dir,
        args.frames,
    )
    reference, tf_seconds = run_tensorflow_reference(
        tf,
        fixed_saved_model,
        embeddings,
    )
    print("Validation embeddings:", embedding_source)
    print("TensorFlow reference shape:", reference.shape)

    report: dict[str, Any] = {
        "format": "spectrostream_litert_export_v1",
        "tensorflow_version": tf.__version__,
        "source_saved_model": str(saved_model_dir),
        "fixed_saved_model": str(fixed_saved_model),
        "frames": args.frames,
        "duration_seconds": args.frames / FRAME_RATE,
        "embedding_dim": EMBEDDING_DIM,
        "sample_rate": SAMPLE_RATE,
        "channels": 2,
        "samples_per_frame": SAMPLES_PER_FRAME,
        "test_embedding_source": embedding_source,
        "tensorflow_reference_seconds": tf_seconds,
        "models": {},
    }

    precisions = ["fp32"] + ([] if args.no_fp16 else ["fp16"])
    allow_flex = not args.no_flex_fallback

    for precision in precisions:
        print(f"\nExporting {precision.upper()}...")
        conversion, model_path = attempt_conversion(
            tf=tf,
            fixed_saved_model=fixed_saved_model,
            models_dir=models_dir,
            frames=args.frames,
            precision=precision,
            allow_flex_fallback=allow_flex,
            force=args.force,
        )
        validation = validate_tflite(
            tf=tf,
            model_path=model_path,
            embeddings=embeddings,
            reference=reference,
            threads=args.threads,
            runs=args.runs,
        )
        conversion["validation"] = validation
        report["models"][precision] = conversion

        comparison = validation["comparison"]
        flex_ops = validation["operators"]["flex_operators"]
        median = validation["inference_seconds"]["median"]
        print(
            f"{precision.upper()} OK: "
            f"{model_path.stat().st_size / 1024**2:.2f} MiB, "
            f"median={median:.4f}s, "
            f"max_abs={comparison['max_abs_error']:.3e}, "
            f"RMSE={comparison['rmse']:.3e}, "
            f"SNR={comparison['snr_db']:.2f} dB"
        )
        if flex_ops:
            print("Flex operators:", ", ".join(flex_ops))
        else:
            print("Operator set: LiteRT builtins only")

        # FP32 conversion should be numerically very close to TensorFlow.
        if precision == "fp32":
            if (
                comparison["max_abs_error"] > 1e-3
                or comparison["rmse"] > 1e-4
            ):
                raise RuntimeError(
                    "FP32 LiteRT validation is too far from TensorFlow: "
                    f"{comparison}"
                )

    report_path = models_dir / f"litert_export_f{args.frames}.json"
    atomic_json(report_path, report)

    print("\nLiteRT export complete")
    print("Report:", report_path)
    for precision, model in report["models"].items():
        print(
            f"  {precision}: {model['path']} "
            f"({model['bytes'] / 1024**2:.2f} MiB, "
            f"{model['operator_mode']})"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
