import 'dart:async';
import 'dart:ffi';
import 'dart:isolate';

import 'package:ffi/ffi.dart';
import 'package:flutter/foundation.dart';

class NeuralDecodeRequest {
  const NeuralDecodeRequest({
    required this.modelPath,
    required this.codebooksPath,
    required this.windowPath,
    required this.sstPath,
    required this.threads,
    required this.cores,
  });

  final String modelPath;
  final String codebooksPath;
  final String windowPath;
  final String sstPath;
  final int threads;
  final int cores;

  String get cacheKey =>
      '$modelPath|$codebooksPath|$windowPath|$threads|$cores';

  Map<String, Object> toMap() {
    return {
      'modelPath': modelPath,
      'codebooksPath': codebooksPath,
      'windowPath': windowPath,
      'sstPath': sstPath,
      'threads': threads,
      'cores': cores,
    };
  }

  static NeuralDecodeRequest fromMap(Map<String, Object?> map) {
    return NeuralDecodeRequest(
      modelPath: map['modelPath']! as String,
      codebooksPath: map['codebooksPath']! as String,
      windowPath: map['windowPath']! as String,
      sstPath: map['sstPath']! as String,
      threads: map['threads']! as int,
      cores: (map['cores'] as int?) ?? 0,
    );
  }
}

class FirstBlockDecodeResult {
  const FirstBlockDecodeResult({
    required this.pcm,
    required this.frameCount,
    required this.sampleRate,
    required this.channels,
    required this.blocksRemaining,
    required this.currentBlockIndex,
    required this.totalBlocks,
    required this.totalPcmFrames,
    required this.blockPcmFrames,
    required this.canceled,
    required this.done,
    required this.decoderReused,
  });

  final Float32List pcm;
  final int frameCount;
  final int sampleRate;
  final int channels;
  final int blocksRemaining;
  final int currentBlockIndex;
  final int totalBlocks;
  final int totalPcmFrames;
  final int blockPcmFrames;
  final bool canceled;
  final bool done;
  final bool decoderReused;
}

class StreamBlockDecodeResult {
  const StreamBlockDecodeResult({
    required this.pcm,
    required this.frameCount,
    required this.sampleRate,
    required this.channels,
    required this.blocksRemaining,
    required this.currentBlockIndex,
    required this.totalBlocks,
    required this.canceled,
    required this.done,
  });

  final Float32List pcm;
  final int frameCount;
  final int sampleRate;
  final int channels;
  final int blocksRemaining;
  final int currentBlockIndex;
  final int totalBlocks;
  final bool canceled;
  final bool done;
}

class StreamSessionInfo {
  const StreamSessionInfo({
    required this.sampleRate,
    required this.channels,
    required this.totalBlocks,
    required this.totalPcmFrames,
    required this.blockPcmFrames,
  });

  final int sampleRate;
  final int channels;
  final int totalBlocks;
  final int totalPcmFrames;
  final int blockPcmFrames;

  Map<String, Object> toMap() {
    return {
      'sampleRate': sampleRate,
      'channels': channels,
      'totalBlocks': totalBlocks,
      'totalPcmFrames': totalPcmFrames,
      'blockPcmFrames': blockPcmFrames,
    };
  }

  static StreamSessionInfo fromMap(Map<String, Object?> map) {
    return StreamSessionInfo(
      sampleRate: map['sampleRate']! as int,
      channels: map['channels']! as int,
      totalBlocks: map['totalBlocks']! as int,
      totalPcmFrames: map['totalPcmFrames']! as int,
      blockPcmFrames: map['blockPcmFrames']! as int,
    );
  }
}

class BackgroundDecodeResult {
  const BackgroundDecodeResult({
    required this.totalFramesDecoded,
    required this.blocksDecoded,
    required this.canceled,
  });

  final int totalFramesDecoded;
  final int blocksDecoded;
  final bool canceled;
}

class SpectroStreamDecoderService {
  SpectroStreamDecoderService._();

  static final SpectroStreamDecoderService instance =
      SpectroStreamDecoderService._();

  Isolate? _worker;
  ReceivePort? _receivePort;
  SendPort? _workerSendPort;
  StreamSubscription<dynamic>? _receiveSubscription;

  int _nextRequestId = 1;
  final Map<int, Completer<Map<String, Object?>>> _pending = {};

  Future<void> ensureStarted() async {
    if (_workerSendPort != null) {
      return;
    }

    _receivePort = ReceivePort();
    final ready = Completer<SendPort>();

    _receiveSubscription = _receivePort!.listen((dynamic message) {
      if (message is SendPort && !ready.isCompleted) {
        ready.complete(message);
        return;
      }
      if (message is Map) {
        _handleWorkerMessage(message.cast<Object?, Object?>());
      }
    });

    _worker = await Isolate.spawn(_decoderWorkerMain, _receivePort!.sendPort);
    _workerSendPort = await ready.future;
  }

  Future<void> preloadDecoder(NeuralDecodeRequest request) async {
    await ensureStarted();
    await _sendCommand('ensure_decoder', request.toMap());
  }

  Future<FirstBlockDecodeResult> startSession(
    NeuralDecodeRequest request,
  ) async {
    await ensureStarted();
    final data = await _sendCommand('start_session', request.toMap());

    return FirstBlockDecodeResult(
      pcm: data['pcm'] as Float32List,
      frameCount: data['frameCount'] as int,
      sampleRate: data['sampleRate'] as int,
      channels: data['channels'] as int,
      blocksRemaining: data['blocksRemaining'] as int,
      currentBlockIndex: data['currentBlockIndex'] as int,
      totalBlocks: data['totalBlocks'] as int,
      totalPcmFrames: data['totalPcmFrames'] as int,
      blockPcmFrames: data['blockPcmFrames'] as int,
      canceled: data['canceled'] as bool,
      done: data['done'] as bool,
      decoderReused: data['decoderReused'] as bool,
    );
  }

  Future<BackgroundDecodeResult> decodeRemaining() async {
    await ensureStarted();
    final data = await _sendCommand('decode_remaining', const {});

    return BackgroundDecodeResult(
      totalFramesDecoded: data['totalFramesDecoded'] as int,
      blocksDecoded: data['blocksDecoded'] as int,
      canceled: data['canceled'] as bool,
    );
  }

  Future<StreamBlockDecodeResult> decodeNextBlock() async {
    await ensureStarted();
    final data = await _sendCommand('decode_next_block', const {});
    return StreamBlockDecodeResult(
      pcm: data['pcm'] as Float32List,
      frameCount: data['frameCount'] as int,
      sampleRate: data['sampleRate'] as int,
      channels: data['channels'] as int,
      blocksRemaining: data['blocksRemaining'] as int,
      currentBlockIndex: data['currentBlockIndex'] as int,
      totalBlocks: data['totalBlocks'] as int,
      canceled: data['canceled'] as bool,
      done: data['done'] as bool,
    );
  }

  Future<void> resetSession({
    Duration timeout = const Duration(milliseconds: 250),
  }) async {
    if (_workerSendPort == null) {
      return;
    }
    try {
      await _sendCommand('reset_session', const {}).timeout(timeout);
    } catch (_) {
      await interruptCurrentWork();
    }
  }

  Future<void> interruptCurrentWork() async {
    await _shutdown(graceful: false);
  }

  Future<void> dispose() async {
    await _shutdown(graceful: true);
  }

  Future<void> _shutdown({required bool graceful}) async {
    if (_workerSendPort == null && _worker == null) {
      return;
    }

    if (graceful && _workerSendPort != null) {
      try {
        await _sendCommand(
          'shutdown',
          const {},
        ).timeout(const Duration(milliseconds: 250));
      } catch (_) {
        // Fall back to forced shutdown.
      }
    }

    _worker?.kill(priority: Isolate.immediate);
    _worker = null;
    _workerSendPort = null;

    await _receiveSubscription?.cancel();
    _receiveSubscription = null;
    _receivePort?.close();
    _receivePort = null;

    for (final completer in _pending.values) {
      if (!completer.isCompleted) {
        completer.completeError(StateError('Decoder service interrupted.'));
      }
    }
    _pending.clear();
  }

  Future<Map<String, Object?>> _sendCommand(
    String command,
    Map<String, Object?> payload,
  ) {
    final port = _workerSendPort;
    if (port == null) {
      return Future.error(StateError('Decoder worker is not started.'));
    }

    final requestId = _nextRequestId++;
    final completer = Completer<Map<String, Object?>>();
    _pending[requestId] = completer;

    port.send({'id': requestId, 'command': command, 'payload': payload});

    return completer.future;
  }

  void _handleWorkerMessage(Map<Object?, Object?> raw) {
    final id = raw['id'];
    if (id is! int) {
      return;
    }

    final completer = _pending.remove(id);
    if (completer == null || completer.isCompleted) {
      return;
    }

    final ok = raw['ok'] == true;
    if (ok) {
      final data =
          (raw['data'] as Map<Object?, Object?>?)?.map(
            (key, value) => MapEntry(key as String, value),
          ) ??
          <String, Object?>{};
      completer.complete(data);
    } else {
      final error = raw['error']?.toString() ?? 'Decoder worker error';
      completer.completeError(StateError(error));
    }
  }
}

void _decoderWorkerMain(SendPort mainSendPort) {
  final commandPort = ReceivePort();
  final state = _DecoderWorkerState();

  mainSendPort.send(commandPort.sendPort);

  commandPort.listen((dynamic rawMessage) {
    if (rawMessage is! Map) {
      return;
    }

    final message = rawMessage.cast<Object?, Object?>();
    final requestId = message['id'];
    final command = message['command'];

    if (requestId is! int || command is! String) {
      return;
    }

    final payload =
        (message['payload'] as Map<Object?, Object?>?)?.map(
          (key, value) => MapEntry(key as String, value),
        ) ??
        <String, Object?>{};

    try {
      Map<String, Object?> result;
      switch (command) {
        case 'ensure_decoder':
          result = state.ensureDecoder(NeuralDecodeRequest.fromMap(payload));
          mainSendPort.send({'id': requestId, 'ok': true, 'data': result});
          break;
        case 'start_session':
          result = state.startSession(NeuralDecodeRequest.fromMap(payload));
          mainSendPort.send({'id': requestId, 'ok': true, 'data': result});
          break;
        case 'decode_remaining':
          result = state.decodeRemaining();
          mainSendPort.send({'id': requestId, 'ok': true, 'data': result});
          break;
        case 'decode_next_block':
          result = state.decodeNextBlock();
          mainSendPort.send({'id': requestId, 'ok': true, 'data': result});
          break;
        case 'reset_session':
          state.resetSession();
          mainSendPort.send({'id': requestId, 'ok': true, 'data': const {}});
          break;
        case 'shutdown':
          state.dispose();
          Isolate.exit(mainSendPort, {
            'id': requestId,
            'ok': true,
            'data': const <String, Object?>{},
          });
        default:
          throw StateError('Unknown decoder command: $command');
      }
    } catch (e) {
      mainSendPort.send({'id': requestId, 'ok': false, 'error': e.toString()});
    }
  });
}

class _DecoderWorkerState {
  late final _NativeBindings _bindings = _NativeBindings();

  Pointer<Void> _decoderHandle = nullptr;
  String? _decoderKey;
  Pointer<Void> _streamHandle = nullptr;

  Map<String, Object?> ensureDecoder(NeuralDecodeRequest request) {
    final key = request.cacheKey;
    final reused = (_decoderHandle != nullptr && _decoderKey == key);

    if (!reused) {
      _destroyStream();
      _destroyDecoder();
      _decoderHandle = _bindings.createDecoder(request);
      _decoderKey = key;
    }

    return {'reused': reused};
  }

  Map<String, Object?> startSession(NeuralDecodeRequest request) {
    final ensureData = ensureDecoder(request);
    final reused = ensureData['reused'] as bool;

    _destroyStream();
    _streamHandle = _bindings.createStream(_decoderHandle, request.sstPath);
    final info = _bindings.getStreamInfo(_streamHandle);

    final firstBlock = _decodeNext();
    return {...firstBlock, ...info.toMap(), 'decoderReused': reused};
  }

  Map<String, Object?> decodeRemaining() {
    if (_streamHandle == nullptr) {
      throw StateError('No active stream session.');
    }

    int totalFramesDecoded = 0;
    int blocksDecoded = 0;
    bool canceled = false;

    while (true) {
      final block = _decodeNext();
      final frameCount = block['frameCount'] as int;
      final done = block['done'] as bool;
      canceled = block['canceled'] as bool;

      if (frameCount > 0) {
        totalFramesDecoded += frameCount;
        blocksDecoded += 1;
      }

      if (done) {
        _destroyStream();
        break;
      }
    }

    return {
      'totalFramesDecoded': totalFramesDecoded,
      'blocksDecoded': blocksDecoded,
      'canceled': canceled,
    };
  }

  Map<String, Object?> decodeNextBlock() {
    if (_streamHandle == nullptr) {
      throw StateError('No active stream session.');
    }

    final block = _decodeNext();
    final done = block['done'] as bool;
    if (done) {
      _destroyStream();
    }
    return block;
  }

  void resetSession() {
    if (_streamHandle != nullptr) {
      _bindings.cancelStream(_streamHandle);
    }
    _destroyStream();
  }

  void dispose() {
    _destroyStream();
    _destroyDecoder();
  }

  Map<String, Object?> _decodeNext() {
    final stopwatch = Stopwatch()..start();
    final pcmOut = calloc<Pointer<Float>>();
    final frameOut = calloc<Int64>();
    final sampleRateOut = calloc<Int32>();
    final channelsOut = calloc<Int32>();
    final remainingOut = calloc<Int32>();
    final doneOut = calloc<Int32>();
    final blockIndexOut = calloc<Int32>();
    final totalBlocksOut = calloc<Int32>();
    final canceledOut = calloc<Int32>();

    Pointer<Float> nativePcm = nullptr;

    try {
      final rc = _bindings.streamDecodeNextEx(
        _streamHandle,
        pcmOut,
        frameOut,
        sampleRateOut,
        channelsOut,
        remainingOut,
        doneOut,
        blockIndexOut,
        totalBlocksOut,
        canceledOut,
      );
      if (rc != 0) {
        throw StateError(_bindings.streamLastError(_streamHandle));
      }

      nativePcm = pcmOut.value;
      final frameCount = frameOut.value;
      final sampleRate = sampleRateOut.value;
      final channels = channelsOut.value;
      final blocksRemaining = remainingOut.value;
      final done = doneOut.value != 0;
      final currentBlockIndex = blockIndexOut.value;
      final totalBlocks = totalBlocksOut.value;
      final canceled = canceledOut.value != 0;

      Float32List pcm = Float32List(0);
      if (nativePcm != nullptr && frameCount > 0 && channels > 0) {
        final sampleCount = frameCount * channels;
        pcm = Float32List.fromList(nativePcm.asTypedList(sampleCount));
      }

      stopwatch.stop();
      debugPrint(
        '[spect] block=$currentBlockIndex/$totalBlocks '
        'frames=$frameCount decode=${stopwatch.elapsedMilliseconds}ms done=$done',
      );

      return {
        'pcm': pcm,
        'frameCount': frameCount,
        'sampleRate': sampleRate,
        'channels': channels,
        'blocksRemaining': blocksRemaining,
        'currentBlockIndex': currentBlockIndex,
        'totalBlocks': totalBlocks,
        'canceled': canceled,
        'done': done,
      };
    } finally {
      if (nativePcm != nullptr) {
        _bindings.freePcm(nativePcm);
      }
      calloc.free(pcmOut);
      calloc.free(frameOut);
      calloc.free(sampleRateOut);
      calloc.free(channelsOut);
      calloc.free(remainingOut);
      calloc.free(doneOut);
      calloc.free(blockIndexOut);
      calloc.free(totalBlocksOut);
      calloc.free(canceledOut);
    }
  }

  void _destroyStream() {
    if (_streamHandle != nullptr) {
      _bindings.destroyStream(_streamHandle);
      _streamHandle = nullptr;
    }
  }

  void _destroyDecoder() {
    if (_decoderHandle != nullptr) {
      _bindings.destroyDecoder(_decoderHandle);
      _decoderHandle = nullptr;
      _decoderKey = null;
    }
  }
}

class _NativeBindings {
  _NativeBindings()
    : _lib = DynamicLibrary.open('libspectrostream_decoder.so') {
    _create = _lib.lookupFunction<_NativeCreate, _DartCreate>(
      'spectrostream_decoder_create_ex',
    );
    _freePcm = _lib.lookupFunction<_NativeFreePcm, _DartFreePcm>(
      'spectrostream_decoder_free_pcm',
    );
    _destroy = _lib.lookupFunction<_NativeDestroy, _DartDestroy>(
      'spectrostream_decoder_destroy',
    );
    _lastError = _lib.lookupFunction<_NativeLastError, _DartLastError>(
      'spectrostream_decoder_last_error',
    );
    _streamCreate = _lib.lookupFunction<_NativeStreamCreate, _DartStreamCreate>(
      'spectrostream_decoder_stream_create',
    );
    _streamDecodeNextEx = _lib
        .lookupFunction<_NativeStreamDecodeNextEx, _DartStreamDecodeNextEx>(
          'spectrostream_decoder_stream_decode_next_ex',
        );
    _streamGetInfo = _lib
        .lookupFunction<_NativeStreamGetInfo, _DartStreamGetInfo>(
          'spectrostream_decoder_stream_get_info',
        );
    _streamCancel = _lib.lookupFunction<_NativeStreamCancel, _DartStreamCancel>(
      'spectrostream_decoder_stream_cancel',
    );
    _streamLastError = _lib
        .lookupFunction<_NativeStreamLastError, _DartStreamLastError>(
          'spectrostream_decoder_stream_last_error',
        );
    _streamDestroy = _lib
        .lookupFunction<_NativeStreamDestroy, _DartStreamDestroy>(
          'spectrostream_decoder_stream_destroy',
        );
  }

  final DynamicLibrary _lib;

  late final _DartCreate _create;
  late final _DartFreePcm _freePcm;
  late final _DartDestroy _destroy;
  late final _DartLastError _lastError;
  late final _DartStreamCreate _streamCreate;
  late final _DartStreamDecodeNextEx _streamDecodeNextEx;
  late final _DartStreamGetInfo _streamGetInfo;
  late final _DartStreamCancel _streamCancel;
  late final _DartStreamLastError _streamLastError;
  late final _DartStreamDestroy _streamDestroy;

  Pointer<Void> createDecoder(NeuralDecodeRequest request) {
    final model = request.modelPath.toNativeUtf8();
    final codebooks = request.codebooksPath.toNativeUtf8();
    final window = request.windowPath.toNativeUtf8();

    try {
      final handle = _create(
        model,
        codebooks,
        window,
        request.threads,
        request.cores,
      );
      if (handle == nullptr) {
        throw StateError('Unable to create decoder handle.');
      }
      final initError = lastError(handle);
      if (initError.isNotEmpty) {
        throw StateError(initError);
      }
      return handle;
    } finally {
      malloc.free(model);
      malloc.free(codebooks);
      malloc.free(window);
    }
  }

  Pointer<Void> createStream(Pointer<Void> handle, String sstPath) {
    final sst = sstPath.toNativeUtf8();
    try {
      final stream = _streamCreate(handle, sst);
      if (stream == nullptr) {
        throw StateError(lastError(handle));
      }
      return stream;
    } finally {
      malloc.free(sst);
    }
  }

  StreamSessionInfo getStreamInfo(Pointer<Void> stream) {
    final infoPtr = calloc<_NativeStreamInfo>();
    try {
      final rc = _streamGetInfo(stream, infoPtr);
      if (rc != 0) {
        throw StateError(streamLastError(stream));
      }
      final info = infoPtr.ref;
      return StreamSessionInfo(
        sampleRate: info.sampleRate,
        channels: info.channels,
        totalBlocks: info.totalBlocks,
        totalPcmFrames: info.totalPcmFrames,
        blockPcmFrames: info.blockPcmFrames,
      );
    } finally {
      calloc.free(infoPtr);
    }
  }

  int streamDecodeNextEx(
    Pointer<Void> stream,
    Pointer<Pointer<Float>> pcmOut,
    Pointer<Int64> frameCountOut,
    Pointer<Int32> sampleRateOut,
    Pointer<Int32> channelsOut,
    Pointer<Int32> blocksRemainingOut,
    Pointer<Int32> doneOut,
    Pointer<Int32> currentBlockIndexOut,
    Pointer<Int32> totalBlocksOut,
    Pointer<Int32> canceledOut,
  ) {
    return _streamDecodeNextEx(
      stream,
      pcmOut,
      frameCountOut,
      sampleRateOut,
      channelsOut,
      blocksRemainingOut,
      doneOut,
      currentBlockIndexOut,
      totalBlocksOut,
      canceledOut,
    );
  }

  void cancelStream(Pointer<Void> stream) {
    final rc = _streamCancel(stream);
    if (rc != 0) {
      throw StateError(streamLastError(stream));
    }
  }

  String lastError(Pointer<Void> handle) {
    final ptr = _lastError(handle);
    if (ptr == nullptr) {
      return '';
    }
    return ptr.toDartString();
  }

  String streamLastError(Pointer<Void> stream) {
    final ptr = _streamLastError(stream);
    if (ptr == nullptr) {
      return '';
    }
    return ptr.toDartString();
  }

  void freePcm(Pointer<Float> pcm) {
    _freePcm(pcm);
  }

  void destroyDecoder(Pointer<Void> handle) {
    if (handle != nullptr) {
      _destroy(handle);
    }
  }

  void destroyStream(Pointer<Void> stream) {
    if (stream != nullptr) {
      _streamDestroy(stream);
    }
  }
}

typedef _NativeCreate =
    Pointer<Void> Function(
      Pointer<Utf8>,
      Pointer<Utf8>,
      Pointer<Utf8>,
      Int32,
      Int32,
    );
typedef _DartCreate =
    Pointer<Void> Function(
      Pointer<Utf8>,
      Pointer<Utf8>,
      Pointer<Utf8>,
      int,
      int,
    );

typedef _NativeFreePcm = Void Function(Pointer<Float>);
typedef _DartFreePcm = void Function(Pointer<Float>);

typedef _NativeDestroy = Void Function(Pointer<Void>);
typedef _DartDestroy = void Function(Pointer<Void>);

typedef _NativeLastError = Pointer<Utf8> Function(Pointer<Void>);
typedef _DartLastError = Pointer<Utf8> Function(Pointer<Void>);

typedef _NativeStreamCreate =
    Pointer<Void> Function(Pointer<Void>, Pointer<Utf8>);
typedef _DartStreamCreate =
    Pointer<Void> Function(Pointer<Void>, Pointer<Utf8>);

typedef _NativeStreamDecodeNextEx =
    Int32 Function(
      Pointer<Void>,
      Pointer<Pointer<Float>>,
      Pointer<Int64>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
    );
typedef _DartStreamDecodeNextEx =
    int Function(
      Pointer<Void>,
      Pointer<Pointer<Float>>,
      Pointer<Int64>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
      Pointer<Int32>,
    );

typedef _NativeStreamGetInfo =
    Int32 Function(Pointer<Void>, Pointer<_NativeStreamInfo>);
typedef _DartStreamGetInfo =
    int Function(Pointer<Void>, Pointer<_NativeStreamInfo>);

typedef _NativeStreamCancel = Int32 Function(Pointer<Void>);
typedef _DartStreamCancel = int Function(Pointer<Void>);

typedef _NativeStreamLastError = Pointer<Utf8> Function(Pointer<Void>);
typedef _DartStreamLastError = Pointer<Utf8> Function(Pointer<Void>);

typedef _NativeStreamDestroy = Void Function(Pointer<Void>);
typedef _DartStreamDestroy = void Function(Pointer<Void>);

final class _NativeStreamInfo extends Struct {
  @Int32()
  external int sampleRate;

  @Int32()
  external int channels;

  @Int32()
  external int totalBlocks;

  @Int64()
  external int totalPcmFrames;

  @Int32()
  external int blockPcmFrames;
}
