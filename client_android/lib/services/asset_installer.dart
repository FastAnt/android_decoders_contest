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
  });

  final Directory rootDirectory;
  final Map<NeuralModelPreset, String> modelPaths;
  final String codebooksPath;
  final String windowPath;
  final String sstPath;
  final int sstSizeBytes;
  final double sstDurationSeconds;
  final int mp3SizeBytes;

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
  };

  static const double _sstDurationSeconds = 162.075;

  Future<InstalledAssets> ensureInstalled() async {
    final supportDir = await getApplicationSupportDirectory();
    final targetDir = Directory('${supportDir.path}/spectrostream');
    if (!await targetDir.exists()) {
      await targetDir.create(recursive: true);
    }

    final stateFile = File('${targetDir.path}/install_state.json');
    final stateSizes = await _readStateSizes(stateFile);

    bool isValid = true;
    if (stateSizes.isEmpty) {
      isValid = false;
    } else {
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
        jsonEncode({'sizes': installedSizes}),
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
    );
  }

  Future<Map<String, int>> _readStateSizes(File stateFile) async {
    if (!await stateFile.exists()) {
      return {};
    }
    try {
      final decoded =
          jsonDecode(await stateFile.readAsString()) as Map<String, dynamic>;
      final raw = decoded['sizes'];
      if (raw is! Map<String, dynamic>) {
        return {};
      }
      return raw.map((key, value) => MapEntry(key, value as int));
    } catch (_) {
      return {};
    }
  }
}
