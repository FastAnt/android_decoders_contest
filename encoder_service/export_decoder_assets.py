#!/usr/bin/env python3
"""Export portable SpectroStream decoder assets.

This version intentionally exports the neural decoder only up to the inputs of
TensorFlow's Complex op. The final complex spectrum -> PCM step (IRFFT,
windowing and overlap-add) is implemented separately in C++.

Outputs:
  rvq_codebooks.npy
  rvq_codebooks.f32
  rvq_codebooks.json
  decoder_savedmodel/
  spectrostream_decoder_spectrum.onnx
  decoder_spectrum_reference.npz
  decoder_export.json
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

# Export is intentionally CPU-only.
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tf
from tensorflow.python.framework.convert_to_constants import (
    convert_variables_to_constants_v2,
)

from magenta_rt import spectrostream


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "decoder_cpp/models"
EXPECTED_CODEBOOK_SHAPE = (64, 1024, 256)
ONNX_NAME = "spectrostream_decoder_spectrum.onnx"
VERSION = "2.0.0-spectrum-split"


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def tensor_name(reference: str) -> str:
    reference = reference.lstrip("^")
    return reference if ":" in reference else f"{reference}:0"


def extract_single_tensor(value: Any) -> tf.Tensor:
    if isinstance(value, dict):
        if len(value) != 1:
            raise RuntimeError(
                f"Expected one decoder output, got keys {list(value)}"
            )
        value = next(iter(value.values()))
    elif isinstance(value, (tuple, list)):
        if len(value) != 1:
            raise RuntimeError(
                f"Expected one decoder output, got {len(value)} outputs"
            )
        value = value[0]

    return value if tf.is_tensor(value) else tf.convert_to_tensor(value)


class DecoderExportModule(tf.Module):
    def __init__(self, decoder: Any) -> None:
        super().__init__(name="spectrostream_decoder")
        self.decoder = decoder

        @tf.function(autograph=False)
        def decode(embeddings: tf.Tensor) -> dict[str, tf.Tensor]:
            audio = extract_single_tensor(self.decoder(embeddings))
            return {"audio": tf.identity(tf.cast(audio, tf.float32), name="audio")}

        self.decode = decode


def create_input_spec(fixed_frames: int | None) -> tf.TensorSpec:
    return tf.TensorSpec(
        shape=[1, fixed_frames, 256],
        dtype=tf.float32,
        name="embeddings",
    )


def export_codebooks(
    codec: spectrostream.SpectroStream,
    output_dir: Path,
) -> dict[str, Any]:
    print("Loading and exporting RVQ codebooks...")
    started = time.perf_counter()

    codebooks = np.asarray(codec.rvq_codebooks, dtype=np.float32)
    codebooks = np.ascontiguousarray(codebooks.astype("<f4", copy=False))

    if codebooks.shape != EXPECTED_CODEBOOK_SHAPE:
        raise RuntimeError(
            f"Unexpected codebook shape {codebooks.shape}, "
            f"expected {EXPECTED_CODEBOOK_SHAPE}"
        )
    if not np.isfinite(codebooks).all():
        raise RuntimeError("Codebooks contain NaN or Inf")

    npy_path = output_dir / "rvq_codebooks.npy"
    raw_path = output_dir / "rvq_codebooks.f32"
    metadata_path = output_dir / "rvq_codebooks.json"

    np.save(npy_path, codebooks, allow_pickle=False)
    codebooks.tofile(raw_path)

    expected_bytes = int(np.prod(EXPECTED_CODEBOOK_SHAPE) * 4)
    if raw_path.stat().st_size != expected_bytes:
        raise RuntimeError(
            f"Raw codebook size {raw_path.stat().st_size} != {expected_bytes}"
        )

    metadata = {
        "format": "spectrostream_rvq_codebooks_v1",
        "shape": list(codebooks.shape),
        "dtype": "float32",
        "endianness": "little",
        "layout": "C-order [rvq_depth][codebook_entry][embedding_dim]",
        "rvq_depth": 64,
        "codebook_size": 1024,
        "embedding_dim": 256,
        "raw_bytes": raw_path.stat().st_size,
        "raw_sha256": sha256_file(raw_path),
        "npy_sha256": sha256_file(npy_path),
    }
    atomic_json(metadata_path, metadata)

    print(
        f"Codebooks ready in {time.perf_counter() - started:.2f}s "
        f"({raw_path.stat().st_size / 1024**2:.2f} MiB)"
    )
    return metadata


def export_wrapped_savedmodel(
    codec: spectrostream.SpectroStream,
    output_dir: Path,
    input_spec: tf.TensorSpec,
    force: bool,
) -> tuple[DecoderExportModule, tf.types.experimental.ConcreteFunction, Path]:
    print("Loading SpectroStream neural decoder...")
    started = time.perf_counter()

    # Deliberately load only the decoder, never the encoder.
    module = DecoderExportModule(codec._decoder)
    concrete = module.decode.get_concrete_function(input_spec)

    test_frames = input_spec.shape[1] or 25
    test_audio = concrete(
        tf.zeros([1, test_frames, 256], dtype=tf.float32)
    )["audio"]
    expected_shape = (1, test_frames * 1920, 2)
    if tuple(test_audio.shape) != expected_shape:
        raise RuntimeError(
            f"Unexpected decoder shape {tuple(test_audio.shape)}, "
            f"expected {expected_shape}"
        )

    savedmodel_dir = output_dir / "decoder_savedmodel"
    if savedmodel_dir.exists():
        if not force:
            print(f"Reusing existing {savedmodel_dir}")
            return module, concrete, savedmodel_dir
        shutil.rmtree(savedmodel_dir)

    tf.saved_model.save(
        module,
        str(savedmodel_dir),
        signatures={"serving_default": concrete},
    )

    print(
        f"Wrapped SavedModel ready in {time.perf_counter() - started:.2f}s"
    )
    return module, concrete, savedmodel_dir


def freeze_and_find_spectrum_cut(
    concrete: tf.types.experimental.ConcreteFunction,
) -> tuple[
    tf.compat.v1.GraphDef,
    str,
    str,
    str,
    str,
]:
    print("Freezing TensorFlow graph and locating Complex/IRFFT boundary...")
    frozen = convert_variables_to_constants_v2(
        concrete,
        lower_control_flow=False,
    )
    graph_def = frozen.graph.as_graph_def(add_shapes=True)

    data_inputs = [
        tensor.name
        for tensor in frozen.inputs
        if tensor.dtype != tf.resource
    ]
    if len(data_inputs) != 1:
        raise RuntimeError(
            f"Expected exactly one frozen data input, got {data_inputs}"
        )
    input_name = data_inputs[0]

    complex_nodes = [
        node for node in graph_def.node if node.op == "Complex"
    ]
    irfft_nodes = [
        node for node in graph_def.node
        if node.op in {"IRFFT", "IRFFT2D", "IRFFT3D"}
    ]

    if len(complex_nodes) != 1:
        names = [node.name for node in complex_nodes]
        raise RuntimeError(
            f"Expected exactly one Complex node, got {len(names)}: {names}"
        )
    if len(irfft_nodes) != 1:
        names = [node.name for node in irfft_nodes]
        raise RuntimeError(
            f"Expected exactly one IRFFT node, got {len(names)}: {names}"
        )

    complex_node = complex_nodes[0]
    irfft_node = irfft_nodes[0]

    if len(complex_node.input) != 2:
        raise RuntimeError(
            f"Complex node has {len(complex_node.input)} inputs, expected 2"
        )

    real_name = tensor_name(complex_node.input[0])
    imag_name = tensor_name(complex_node.input[1])

    print("Frozen input:", input_name)
    print("Complex node:", complex_node.name)
    print("IRFFT node:", irfft_node.name)
    print("Spectrum real tensor:", real_name)
    print("Spectrum imag tensor:", imag_name)

    return (
        graph_def,
        input_name,
        real_name,
        imag_name,
        irfft_node.name,
    )


def make_tf_cut_function(
    graph_def: tf.compat.v1.GraphDef,
    input_name: str,
    real_name: str,
    imag_name: str,
):
    def import_graph() -> None:
        tf.compat.v1.import_graph_def(graph_def, name="")

    wrapped = tf.compat.v1.wrap_function(import_graph, [])
    graph = wrapped.graph

    feed = graph.get_tensor_by_name(input_name)
    real = graph.get_tensor_by_name(real_name)
    imag = graph.get_tensor_by_name(imag_name)

    return wrapped.prune(
        feeds=[feed],
        fetches=[real, imag],
    )


def export_spectrum_onnx(
    graph_def: tf.compat.v1.GraphDef,
    input_name: str,
    real_name: str,
    imag_name: str,
    output_dir: Path,
    opset: int,
    force: bool,
) -> Path:
    try:
        import tf2onnx
        import onnx
    except ImportError as error:
        raise RuntimeError(
            "Install conversion dependencies with: "
            "python -m pip install --upgrade tf2onnx onnx onnxruntime"
        ) from error

    onnx_path = output_dir / ONNX_NAME
    if onnx_path.exists():
        if not force:
            raise FileExistsError(
                f"{onnx_path} already exists; use --force"
            )
        onnx_path.unlink()

    print(f"Exporting neural spectrum model to ONNX opset {opset}...")
    started = time.perf_counter()

    tf2onnx.convert.from_graph_def(
        graph_def,
        name="spectrostream_decoder_spectrum",
        input_names=[input_name],
        output_names=[real_name, imag_name],
        opset=opset,
        large_model=False,
        output_path=str(onnx_path),
    )

    if not onnx_path.is_file() or onnx_path.stat().st_size == 0:
        raise RuntimeError("tf2onnx did not create an ONNX file")

    onnx.checker.check_model(str(onnx_path), full_check=True)

    unsupported = {
        node.op_type
        for node in onnx.load(str(onnx_path)).graph.node
        if node.op_type in {"Complex", "IRFFT", "IRFFT2D", "IRFFT3D"}
    }
    if unsupported:
        raise RuntimeError(
            f"Unsupported FFT ops unexpectedly remain in ONNX: {unsupported}"
        )

    print(
        f"ONNX ready in {time.perf_counter() - started:.2f}s "
        f"({onnx_path.stat().st_size / 1024**2:.2f} MiB)"
    )
    return onnx_path


def validate_spectrum_onnx(
    tf_cut,
    onnx_path: Path,
    output_dir: Path,
    test_frames: int,
) -> dict[str, Any]:
    try:
        import onnxruntime as ort
    except ImportError as error:
        raise RuntimeError(
            "Install onnxruntime with: python -m pip install --upgrade onnxruntime"
        ) from error

    print(f"Validating TensorFlow cut vs ONNX on {test_frames} frames...")
    rng = np.random.default_rng(20260711)
    embeddings = rng.normal(
        0.0,
        0.1,
        size=(1, test_frames, 256),
    ).astype(np.float32)

    tf_started = time.perf_counter()
    tf_real_tensor, tf_imag_tensor = tf_cut(tf.constant(embeddings))
    tf_seconds = time.perf_counter() - tf_started

    tf_real = np.asarray(tf_real_tensor, dtype=np.float32)
    tf_imag = np.asarray(tf_imag_tensor, dtype=np.float32)

    session_options = ort.SessionOptions()
    session_options.graph_optimization_level = (
        ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    )
    session = ort.InferenceSession(
        str(onnx_path),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )

    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 2:
        raise RuntimeError(
            f"Expected 1 ONNX input and 2 outputs, got "
            f"{len(inputs)} and {len(outputs)}"
        )

    ort_started = time.perf_counter()
    ort_real, ort_imag = session.run(
        [outputs[0].name, outputs[1].name],
        {inputs[0].name: embeddings},
    )
    ort_seconds = time.perf_counter() - ort_started

    def metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
        if reference.shape != candidate.shape:
            raise RuntimeError(
                f"Shape mismatch {reference.shape} != {candidate.shape}"
            )
        difference = (
            reference.astype(np.float64) - candidate.astype(np.float64)
        )
        return {
            "max_abs_error": float(np.max(np.abs(difference))),
            "mean_abs_error": float(np.mean(np.abs(difference))),
            "rmse": float(np.sqrt(np.mean(np.square(difference)))),
        }

    real_metrics = metrics(tf_real, ort_real)
    imag_metrics = metrics(tf_imag, ort_imag)

    worst_max = max(
        real_metrics["max_abs_error"],
        imag_metrics["max_abs_error"],
    )
    worst_rmse = max(
        real_metrics["rmse"],
        imag_metrics["rmse"],
    )

    if worst_max > 1e-3 or worst_rmse > 1e-4:
        raise RuntimeError(
            "ONNX spectrum validation failed: "
            f"max_abs={worst_max:.6g}, rmse={worst_rmse:.6g}"
        )

    reference_path = output_dir / "decoder_spectrum_reference.npz"
    np.savez_compressed(
        reference_path,
        embeddings=embeddings,
        spectrum_real=tf_real,
        spectrum_imag=tf_imag,
    )

    validation = {
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
        "tensorflow_seconds": tf_seconds,
        "onnx_seconds": ort_seconds,
        "test_frames": test_frames,
        "spectrum_shape": list(tf_real.shape),
        "real": real_metrics,
        "imag": imag_metrics,
        "reference_npz": str(reference_path),
        "reference_sha256": sha256_file(reference_path),
        "passed": True,
    }

    print(
        "Spectrum validation PASSED: "
        f"max_abs={worst_max:.3e}, rmse={worst_rmse:.3e}"
    )
    print("Spectrum shape:", tf_real.shape)
    return validation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export SpectroStream codebooks and neural spectrum decoder "
            "for a portable C++ runtime"
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=18,
    )
    parser.add_argument(
        "--test-frames",
        type=int,
        default=25,
    )
    parser.add_argument(
        "--fixed-frames",
        type=int,
        default=None,
        help="Normally leave unset to export a dynamic frame dimension",
    )
    parser.add_argument(
        "--force",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not 14 <= args.opset <= 18:
        raise ValueError("--opset must be in range 14..18")
    if args.test_frames <= 0:
        raise ValueError("--test-frames must be positive")
    if args.fixed_frames is not None and args.fixed_frames <= 0:
        raise ValueError("--fixed-frames must be positive")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Exporter version:", VERSION)
    print("TensorFlow:", tf.__version__)
    print("Export directory:", output_dir)
    print("CUDA_VISIBLE_DEVICES:", os.environ.get("CUDA_VISIBLE_DEVICES"))

    codec = spectrostream.SpectroStream(
        max_rvq_depth=64,
        lazy=True,
    )

    codebooks_metadata = export_codebooks(codec, output_dir)
    input_spec = create_input_spec(args.fixed_frames)

    module, concrete, savedmodel_dir = export_wrapped_savedmodel(
        codec,
        output_dir,
        input_spec,
        args.force,
    )
    del module

    (
        graph_def,
        input_name,
        real_name,
        imag_name,
        irfft_node_name,
    ) = freeze_and_find_spectrum_cut(concrete)

    tf_cut = make_tf_cut_function(
        graph_def,
        input_name,
        real_name,
        imag_name,
    )

    onnx_path = export_spectrum_onnx(
        graph_def,
        input_name,
        real_name,
        imag_name,
        output_dir,
        args.opset,
        args.force,
    )

    validation = validate_spectrum_onnx(
        tf_cut,
        onnx_path,
        output_dir,
        args.test_frames,
    )

    metadata = {
        "format": "spectrostream_decoder_spectrum_export_v2",
        "exporter_version": VERSION,
        "tensorflow_version": tf.__version__,
        "sample_rate": 48000,
        "channels": 2,
        "codec_frame_rate": 25,
        "embedding_dim": 256,
        "dynamic_frames": args.fixed_frames is None,
        "input_shape": [1, args.fixed_frames, 256],
        "savedmodel_path": str(savedmodel_dir),
        "onnx_path": str(onnx_path),
        "onnx_bytes": onnx_path.stat().st_size,
        "onnx_sha256": sha256_file(onnx_path),
        "opset": args.opset,
        "tensorflow_cut": {
            "input_tensor": input_name,
            "spectrum_real_tensor": real_name,
            "spectrum_imag_tensor": imag_name,
            "irfft_node": irfft_node_name,
        },
        "postprocess_required_in_cpp": [
            "combine real and imaginary spectrum",
            "inverse real FFT",
            "inverse-STFT window",
            "overlap-add",
            "causal padding/cropping compatible with TensorFlow model",
        ],
        "codebooks": codebooks_metadata,
        "validation": validation,
    }
    metadata_path = output_dir / "decoder_export.json"
    atomic_json(metadata_path, metadata)

    print("\nExport complete:")
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            print(
                f"  {path.name:42s} "
                f"{path.stat().st_size / 1024**2:9.2f} MiB"
            )
        else:
            print(f"  {path.name}/")
    print("Metadata:", metadata_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
