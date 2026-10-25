import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import '../models/demo_config.dart';

class InstalledAssets {
  const InstalledAssets({
    required this.rootDirectory,
    required this.modelPaths,
    required this.codebooksPath,
    required this.windowPath,
    required this.sstPath,
    required this.sstSizeBytes,
    required this.sstDurationSeconds,
    required this.mp3SizeBytes,
    required this.sageModelPath,
    required this.sagePath,
    required this.sageSizeBytes,
    required this.sameModelPath,
    required this.samePath,
    required this.sameSizeBytes,
  });

  final Directory rootDirectory;
  final Map<NeuralModelPreset, String> modelPaths;
  final String codebooksPath;
  final String windowPath;
  final String sstPath;
  final int sstSizeBytes;
  final double sstDurationSeconds;
  final int mp3SizeBytes;
  final String sageModelPath;
  final String sagePath;
  final int sageSizeBytes;
  final String sameModelPath;
  final String samePath;
  final int sameSizeBytes;

  int get neuralFirstSecondBytes => (sstSizeBytes / sstDurationSeconds).ceil();
}

class AssetInstaller {
  static const String _mp3Asset = 'assets/audio/demo.mp3';

  static const Map<String, String> _installFiles = {
    'assets/spectrostream/spectrostream_decoder_core_fp32_f25.tflite':
        'spectrostream_decoder_core_fp32_f25.tflite',
    'assets/spectrostream/spectrostream_decoder_core_fp32_f75.tflite':
        'spectrostream_decoder_core_fp32_f75.tflite',
    'assets/spectrostream/spectrostream_decoder_core_fp16_f25.tflite':
        'spectrostream_decoder_core_fp16_f25.tflite',
    'assets/spectrostream/spectrostream_decoder_core_fp16_f75.tflite':
        'spectrostream_decoder_core_fp16_f75.tflite',
    'assets/spectrostream/spectrostream_decoder_core_fp16_f100.tflite':
        'spectrostream_decoder_core_fp16_f100.tflite',
    'assets/spectrostream/rvq_codebooks.f32': 'rvq_codebooks.f32',
    'assets/spectrostream/istft_window_f960.f32': 'istft_window_f960.f32',
    'assets/spectrostream/demo.sst': 'demo.sst',
    'assets/sage/dec_w8a8.tflite': 'sage_dec_w8a8.tflite',
    'assets/sage/demo.sage': 'demo.sage',
    'assets/same/dec_w8a8_s128.tflite': 'same_dec_w8a8_s128.tflite',
    'assets/same/demo.same': 'demo.same',
  };

  static const double _sstDurationSeconds = 133.607625;

  /// Bump when a bundled model or demo file changes. The install state is
  /// keyed by this revision so an app update cannot keep an older model/track.
  static const int _assetRevision = 4;

  Future<InstalledAssets> ensureInstalled() async {
    final supportDir = await getApplicationSupportDirectory();
    final targetDir = Directory('${supportDir.path}/spectrostream');
    if (!await targetDir.exists()) {
      await targetDir.create(recursive: true);
    }

    final stateFile = File('${targetDir.path}/install_state.json');
    final state = await _readState(stateFile);
    final stateSizes = state.sizes;

    bool isValid = state.revision == _assetRevision && stateSizes.isNotEmpty;
    if (isValid) {
      for (final entry in _installFiles.entries) {
        final filename = entry.value;
        final expectedSize = stateSizes[filename];
        if (expectedSize == null) {
          isValid = false;
          break;
        }
        final file = File('${targetDir.path}/$filename');
        if (!await file.exists()) {
          isValid = false;
          break;
        }
        final size = await file.length();
        if (size != expectedSize) {
          isValid = false;
          break;
        }
      }
    }

    Map<String, int> installedSizes = Map<String, int>.from(stateSizes);
    if (!isValid) {
      installedSizes = {};
      for (final entry in _installFiles.entries) {
        final assetPath = entry.key;
        final filename = entry.value;
        final file = File('${targetDir.path}/$filename');

        final data = await rootBundle.load(assetPath);
        final bytes = data.buffer.asUint8List(
          data.offsetInBytes,
          data.lengthInBytes,
        );
        await file.writeAsBytes(bytes, flush: true);
        installedSizes[filename] = bytes.length;
      }
      await stateFile.writeAsString(
        jsonEncode({'revision': _assetRevision, 'sizes': installedSizes}),
        flush: true,
      );
    }

    final mp3SizeBytes = (await rootBundle.load(_mp3Asset)).lengthInBytes;

    return InstalledAssets(
      rootDirectory: targetDir,
      modelPaths: {
        NeuralModelPreset.f25Fp32:
            '${targetDir.path}/spectrostream_decoder_core_fp32_f25.tflite',
        NeuralModelPreset.f25Fp16:
            '${targetDir.path}/spectrostream_decoder_core_fp16_f25.tflite',
        NeuralModelPreset.f75Fp32:
            '${targetDir.path}/spectrostream_decoder_core_fp32_f75.tflite',
        NeuralModelPreset.f75Fp16:
            '${targetDir.path}/spectrostream_decoder_core_fp16_f75.tflite',
        NeuralModelPreset.f100Fp16:
            '${targetDir.path}/spectrostream_decoder_core_fp16_f100.tflite',
      },
      codebooksPath: '${targetDir.path}/rvq_codebooks.f32',
      windowPath: '${targetDir.path}/istft_window_f960.f32',
      sstPath: '${targetDir.path}/demo.sst',
      sstSizeBytes: installedSizes['demo.sst'] ?? 0,
      sstDurationSeconds: _sstDurationSeconds,
      mp3SizeBytes: mp3SizeBytes,
      sageModelPath: '${targetDir.path}/sage_dec_w8a8.tflite',
      sagePath: '${targetDir.path}/demo.sage',
      sageSizeBytes: installedSizes['demo.sage'] ?? 0,
      sameModelPath: '${targetDir.path}/same_dec_w8a8_s128.tflite',
      samePath: '${targetDir.path}/demo.same',
      sameSizeBytes: installedSizes['demo.same'] ?? 0,
    );
  }

  Future<_InstallState> _readState(File stateFile) async {
    if (!await stateFile.exists()) {
      return const _InstallState(0, {});
    }
    try {
      final decoded =
          jsonDecode(await stateFile.readAsString()) as Map<String, dynamic>;
      final revision = (decoded['revision'] as num?)?.toInt() ?? 0;
      final raw = decoded['sizes'];
      if (raw is! Map<String, dynamic>) {
        return _InstallState(revision, const {});
      }
      final sizes = raw.map((key, value) => MapEntry(key, value as int));
      return _InstallState(revision, sizes);
    } catch (_) {
      return const _InstallState(0, {});
    }
  }
}

class _InstallState {
  const _InstallState(this.revision, this.sizes);

  final int revision;
  final Map<String, int> sizes;
}
