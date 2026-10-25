import 'dart:typed_data';

import 'package:flutter/services.dart';

/// One decoded SAME-S core block: interleaved stereo float32 PCM.
class SameChunk {
  const SameChunk({
    required this.pcm,
    required this.frameCount,
    required this.sampleRate,
    required this.channels,
    required this.totalSamples,
    required this.durationSeconds,
    required this.windowsDecoded,
    required this.windowCount,
    required this.done,
    required this.decoderReused,
  });

  final Float32List pcm;
  final int frameCount;
  final int sampleRate;
  final int channels;
  final int totalSamples;
  final double durationSeconds;
  final int windowsDecoded;
  final int windowCount;
  final bool done;
  final bool decoderReused;
}

/// Dart side of the SAME-S MethodChannel bridge.
///
/// Decoding runs on a dedicated Kotlin thread; this service only marshals
/// commands and converts the raw little-endian float32 payload to a
/// [Float32List] for [AudioPlayerService].
class SameDecoderService {
  SameDecoderService._();

  static final SameDecoderService instance = SameDecoderService._();

  static const MethodChannel _channel = MethodChannel('neuralcodecs/same');

  Future<bool> preload({
    required String modelPath,
    required int threads,
    required int cores,
  }) async {
    final data = await _channel.invokeMethod<Map<Object?, Object?>>('preload', {
      'modelPath': modelPath,
      'threads': threads,
      'cores': cores,
    });
    return data?['reused'] == true;
  }

  Future<SameChunk> start({
    required String modelPath,
    required String samePath,
    required int threads,
    required int cores,
  }) async {
    final data = await _channel.invokeMethod<Map<Object?, Object?>>('start', {
      'modelPath': modelPath,
      'samePath': samePath,
      'threads': threads,
      'cores': cores,
    });
    return _toChunk(data);
  }

  Future<SameChunk> next() async {
    final data = await _channel.invokeMethod<Map<Object?, Object?>>('next');
    return _toChunk(data);
  }

  Future<void> stop() async {
    await _channel.invokeMethod<void>('stop');
  }

  Future<void> release() async {
    await _channel.invokeMethod<void>('release');
  }

  Future<void> dispose() async {
    await release();
  }

  SameChunk _toChunk(Map<Object?, Object?>? data) {
    if (data == null) {
      throw StateError('SAME-S returned an empty response.');
    }
    final rawPcm = data['pcm'];
    final pcm = _toFloat32(rawPcm);
    final frameCount = _toInt(data['frameCount']);
    final channels = _toInt(data['channels']);
    if (frameCount > 0 && channels > 0 && pcm.length != frameCount * channels) {
      throw StateError(
        'SAME-S PCM length ${pcm.length} does not match '
        '$frameCount frames x $channels channels.',
      );
    }
    return SameChunk(
      pcm: pcm,
      frameCount: frameCount,
      sampleRate: _toInt(data['sampleRate']),
      channels: channels,
      totalSamples: _toInt(data['totalSamples']),
      durationSeconds: _toDouble(data['durationSeconds']),
      windowsDecoded: _toInt(data['windowsDecoded']),
      windowCount: _toInt(data['windowCount']),
      done: data['done'] == true,
      decoderReused: data['decoderReused'] == true,
    );
  }

  static int _toInt(Object? value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return 0;
  }

  static double _toDouble(Object? value) {
    if (value is double) {
      return value;
    }
    if (value is num) {
      return value.toDouble();
    }
    return 0;
  }

  static Float32List _toFloat32(Object? raw) {
    if (raw is Float32List) {
      return raw;
    }
    if (raw is Uint8List) {
      if (raw.lengthInBytes % 4 != 0) {
        throw StateError('SAME-S PCM byte length is not a multiple of 4.');
      }
      if (raw.offsetInBytes % 4 == 0) {
        return raw.buffer.asFloat32List(
          raw.offsetInBytes,
          raw.lengthInBytes ~/ 4,
        );
      }
      final aligned = Uint8List.fromList(raw);
      return aligned.buffer.asFloat32List(0, aligned.lengthInBytes ~/ 4);
    }
    if (raw is List) {
      return Float32List.fromList(
        raw.map((value) => (value as num).toDouble()).toList(growable: false),
      );
    }
    throw StateError(
      'Unexpected SAME-S PCM payload type: ${raw.runtimeType}',
    );
  }
}
