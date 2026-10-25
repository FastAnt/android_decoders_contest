import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';

class AudioPlayerService {
  AudioPlayerService() : _player = AudioPlayer();

  final AudioPlayer _player;
  final List<String> _neuralChunkPaths = [];
  int _nextChunkIndex = 0;
  int? _neuralSampleRate;
  int? _neuralChannels;

  AudioPlayer get player => _player;

  Future<void> playMp3Asset() async {
    await _resetNeuralChunks();
    await _player.setAsset('assets/audio/demo.mp3');
    // just_audio's play() future completes when playback finishes/pauses;
    // awaiting it here would block the startup measurement until the track ends.
    unawaited(_player.play());
  }

  Future<void> playNeuralStream({
    required Float32List firstBlockPcm,
    required int sampleRate,
    required int channels,
  }) async {
    await _resetNeuralChunks();
    _neuralSampleRate = sampleRate;
    _neuralChannels = channels;

    final firstPath = await _writeNeuralChunkAsWav(
      pcm: firstBlockPcm,
      sampleRate: sampleRate,
      channels: channels,
    );
    await _player.setAudioSources([AudioSource.uri(Uri.file(firstPath))]);
    unawaited(_player.play());
  }

  Future<void> appendNeuralPcm(Float32List pcm) async {
    final sampleRate = _neuralSampleRate;
    final channels = _neuralChannels;
    if (sampleRate == null || channels == null || pcm.isEmpty) {
      return;
    }

    final path = await _writeNeuralChunkAsWav(
      pcm: pcm,
      sampleRate: sampleRate,
      channels: channels,
    );
    await _player.addAudioSource(AudioSource.uri(Uri.file(path)));
  }

  void completeNeuralStream() {
    // Queue-based playback naturally completes when the final chunk ends.
  }

  Future<void> abortNeuralStream() async {
    await _resetNeuralChunks();
  }

  Future<void> waitForPlaybackStart({
    Duration timeout = const Duration(seconds: 5),
  }) async {
    bool isReady(PlayerState state) {
      return state.playing &&
          (state.processingState == ProcessingState.ready ||
              state.processingState == ProcessingState.completed);
    }

    if (isReady(_player.playerState)) {
      return;
    }

    final completer = Completer<void>();
    late final StreamSubscription<PlayerState> stateSub;

    stateSub = _player.playerStateStream.listen((state) {
      if (!completer.isCompleted && isReady(state)) {
        completer.complete();
      }
    });

    try {
      await completer.future.timeout(timeout, onTimeout: () {});
    } finally {
      await stateSub.cancel();
    }
  }

  Future<void> stop() async {
    await _player.stop();
    await _resetNeuralChunks();
  }

  Future<void> pause() async {
    await _player.pause();
  }

  Future<void> resume() async {
    unawaited(_player.play());
  }

  Future<void> dispose() async {
    await _resetNeuralChunks();
    await _player.dispose();
  }

  Future<String> _writeNeuralChunkAsWav({
    required Float32List pcm,
    required int sampleRate,
    required int channels,
  }) async {
    final tempDir = await getTemporaryDirectory();
    final index = _nextChunkIndex++;
    final file = File(
      '${tempDir.path}/spectrostream_chunk_${DateTime.now().microsecondsSinceEpoch}_$index.wav',
    );
    _neuralChunkPaths.add(file.path);

    final bytes = _buildWavBytes(
      pcm: pcm,
      sampleRate: sampleRate,
      channels: channels,
    );
    await file.writeAsBytes(bytes, flush: true);
    return file.path;
  }

  Future<void> _resetNeuralChunks() async {
    _neuralSampleRate = null;
    _neuralChannels = null;
    _nextChunkIndex = 0;

    if (_neuralChunkPaths.isEmpty) {
      return;
    }

    final stale = List<String>.from(_neuralChunkPaths);
    _neuralChunkPaths.clear();
    for (final path in stale) {
      try {
        final file = File(path);
        if (await file.exists()) {
          await file.delete();
        }
      } catch (_) {
        // Best effort cleanup.
      }
    }
  }

  Uint8List _buildWavBytes({
    required Float32List pcm,
    required int sampleRate,
    required int channels,
  }) {
    final totalDataBytes = pcm.length * 2;
    final header = _buildWavHeader(
      sampleRate: sampleRate,
      channels: channels,
      totalDataBytes: totalDataBytes,
    );

    final sampleBytes = ByteData(totalDataBytes);
    for (int i = 0; i < pcm.length; i++) {
      final clamped = pcm[i].clamp(-1.0, 1.0);
      final sample = (clamped * 32767.0).round();
      sampleBytes.setInt16(i * 2, sample, Endian.little);
    }

    final out = Uint8List(44 + totalDataBytes);
    out.setAll(0, header);
    out.setAll(44, sampleBytes.buffer.asUint8List());
    return out;
  }

  Uint8List _buildWavHeader({
    required int sampleRate,
    required int channels,
    required int totalDataBytes,
  }) {
    const bitsPerSample = 16;
    final byteRate = sampleRate * channels * (bitsPerSample ~/ 8);
    final blockAlign = channels * (bitsPerSample ~/ 8);
    final riffSize = 36 + totalDataBytes;

    final header = ByteData(44)
      ..setUint8(0, 0x52)
      ..setUint8(1, 0x49)
      ..setUint8(2, 0x46)
      ..setUint8(3, 0x46)
      ..setUint32(4, riffSize, Endian.little)
      ..setUint8(8, 0x57)
      ..setUint8(9, 0x41)
      ..setUint8(10, 0x56)
      ..setUint8(11, 0x45)
      ..setUint8(12, 0x66)
      ..setUint8(13, 0x6D)
      ..setUint8(14, 0x74)
      ..setUint8(15, 0x20)
      ..setUint32(16, 16, Endian.little)
      ..setUint16(20, 1, Endian.little)
      ..setUint16(22, channels, Endian.little)
      ..setUint32(24, sampleRate, Endian.little)
      ..setUint32(28, byteRate, Endian.little)
      ..setUint16(32, blockAlign, Endian.little)
      ..setUint16(34, bitsPerSample, Endian.little)
      ..setUint8(36, 0x64)
      ..setUint8(37, 0x61)
      ..setUint8(38, 0x74)
      ..setUint8(39, 0x61)
      ..setUint32(40, totalDataBytes, Endian.little);

    return header.buffer.asUint8List();
  }
}
