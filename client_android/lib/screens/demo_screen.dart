import 'dart:async';

import 'package:flutter/material.dart';

import '../models/demo_config.dart';
import '../services/asset_installer.dart';
import '../services/audio_player_service.dart';
import '../services/connection_measurement_service.dart';
import '../services/network_simulator.dart';
import '../services/network_profile_service.dart';
import '../services/sage_decoder_service.dart';
import '../services/same_decoder_service.dart';
import '../services/spectrostream_ffi.dart';
import 'history_screen.dart';
import 'settings_screen.dart';

class DemoScreen extends StatefulWidget {
  const DemoScreen({
    super.key,
    this.isDayStyle = false,
    this.onToggleTheme = _noop,
  });

  final bool isDayStyle;
  final VoidCallback onToggleTheme;

  static void _noop() {}

  @override
  State<DemoScreen> createState() => _DemoScreenState();
}

class _DemoScreenState extends State<DemoScreen> {
  static const int _memoryBlockBytes = 25 * 1024;

  final AssetInstaller _assetInstaller = AssetInstaller();
  final AudioPlayerService _audioService = AudioPlayerService();
  final NetworkProfileService _networkProfileService =
      const NetworkProfileService();
  final ConnectionMeasurementService _connectionMeasurementService =
      const ConnectionMeasurementService();
  final SpectroStreamDecoderService _decoderService =
      SpectroStreamDecoderService.instance;
  final SageDecoderService _sageService = SageDecoderService.instance;
  final SameDecoderService _sameService = SameDecoderService.instance;

  InstalledAssets? _installedAssets;

  NetworkPreset _networkPreset = DemoDefaults.network;
  DemoMode _mode = DemoDefaults.mode;
  NeuralModelPreset _modelPreset = DemoDefaults.model;
  int _threads = DemoDefaults.threads;
  int _cores = DemoDefaults.cores;

  bool _loadingAssets = true;
  bool _isPreparing = false;
  bool _isPlaying = false;
  bool _isPaused = false;

  Duration _liveElapsed = Duration.zero;
  Duration _startupElapsed = Duration.zero;
  int _downloadedBytes = 0;
  int _startupDownloadedBytes = 0;
  double _simulatedSpeedMbps = 0;

  final List<RunHistoryEntry> _recentRuns = [];
  ConnectionMeasurementResult? _currentMeasurement;
  NetworkProfile? _activeRunProfile;

  String _backgroundDecodeStatus = 'IDLE';
  String? _error;

  int _sessionId = 0;
  StreamSubscription<bool>? _playingSubscription;

  @override
  void initState() {
    super.initState();
    _playingSubscription = _audioService.player.playingStream.listen((playing) {
      if (!mounted) {
        return;
      }

      final nextIsPlaying = playing;
      final nextIsPaused = playing ? false : _isPaused;
      if (_isPlaying == nextIsPlaying && _isPaused == nextIsPaused) {
        return;
      }

      setState(() {
        _isPlaying = nextIsPlaying;
        _isPaused = nextIsPaused;
      });
    });
    _initAssets();
  }

  @override
  void dispose() {
    _sessionId += 1;
    unawaited(_playingSubscription?.cancel());
    unawaited(_audioService.dispose());
    unawaited(_decoderService.dispose());
    unawaited(_sageService.dispose());
    unawaited(_sameService.dispose());
    super.dispose();
  }

  Future<void> _initAssets() async {
    try {
      final installed = await _assetInstaller.ensureInstalled();
      if (!mounted) {
        return;
      }
      setState(() {
        _installedAssets = installed;
        _loadingAssets = false;
      });
      unawaited(_warmupDecoder());
    } catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loadingAssets = false;
        _error = 'ASSET INSTALL FAILED: $e';
      });
    }
  }

  NeuralDecodeRequest _buildNeuralRequest(InstalledAssets assets) {
    return NeuralDecodeRequest(
      modelPath: assets.modelPaths[_modelPreset]!,
      codebooksPath: assets.codebooksPath,
      windowPath: assets.windowPath,
      sstPath: assets.sstPath,
      threads: _threads,
      cores: _cores,
    );
  }

  Future<void> _warmupDecoder() async {
    final assets = _installedAssets;
    if (assets == null) {
      return;
    }
    final mode = _mode;
    if (_isPreparing || _isPlaying || _isPaused) {
      return;
    }

    // Only one large neural decoder is kept alive. LiteRT arenas for SAGE and
    // SAME-S and the SpectroStream native decoder are released when another
    // mode is selected. Release failures are non-fatal: the selected codec is
    // still warmed up below.
    if (mode != DemoMode.neuralSage) {
      try {
        await _sageService.release();
      } catch (_) {}
    }
    if (mode != DemoMode.neuralSameS) {
      try {
        await _sameService.release();
      } catch (_) {}
    }
    if (mode != DemoMode.neuralSpect) {
      try {
        await _decoderService.dispose();
      } catch (_) {}
    }

    if (mode == DemoMode.mp3) {
      if (mounted) {
        setState(() {
          _backgroundDecodeStatus = 'IDLE';
        });
      }
      return;
    }

    try {
      switch (mode) {
        case DemoMode.neuralSpect:
          await _decoderService.preloadDecoder(_buildNeuralRequest(assets));
          break;
        case DemoMode.neuralSage:
          await _sageService.preload(
            modelPath: assets.sageModelPath,
            threads: _threads,
            cores: _cores,
          );
          break;
        case DemoMode.neuralSameS:
          await _sameService.preload(
            modelPath: assets.sameModelPath,
            threads: _threads,
            cores: _cores,
          );
          break;
        case DemoMode.mp3:
          break;
      }
      if (!mounted ||
          _mode != mode ||
          _isPreparing ||
          _isPlaying ||
          _isPaused) {
        return;
      }
      setState(() {
        _backgroundDecodeStatus = 'WARMUP DONE';
      });
      debugPrint('[warmup] ${mode.name} T$_threads C$_cores done');
    } catch (e) {
      if (!mounted || _mode != mode) {
        return;
      }
      setState(() {
        _backgroundDecodeStatus = 'WARMUP FAILED: $e';
      });
    }
  }

  bool _isSessionActive(int sessionId) {
    return mounted && _sessionId == sessionId;
  }

  Future<void> _openHistory() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (context) => HistoryScreen(
          runs: List<RunHistoryEntry>.unmodifiable(_recentRuns),
          memoryBlockBytes: _memoryBlockBytes,
        ),
      ),
    );
  }

  Future<void> _openSettings() async {
    final result = await Navigator.of(context).push<DemoSettingsResult>(
      MaterialPageRoute(
        builder: (context) => DemoSettingsScreen(
          initialMode: _mode,
          initialNetworkPreset: _networkPreset,
          initialModelPreset: _modelPreset,
          initialThreads: _threads,
          initialCores: _cores,
        ),
      ),
    );

    if (result == null || !mounted) {
      return;
    }

    // Releasing the previous codec while a stream is active would abort the
    // decode pump. Settings are applied only after a clean stop.
    if (_isPreparing || _isPlaying || _isPaused) {
      await _onStopPressed();
      if (!mounted) {
        return;
      }
    }

    setState(() {
      _mode = result.mode;
      _networkPreset = result.networkPreset;
      _modelPreset = result.modelPreset;
      _threads = result.threads;
      _cores = result.cores;
      if (_networkPreset != NetworkPreset.currentConnection) {
        _currentMeasurement = null;
      }
    });

    unawaited(_warmupDecoder());
  }

  Future<NetworkProfile> _resolveNetworkProfileForRun(int sessionId) async {
    if (_networkPreset != NetworkPreset.currentConnection) {
      return _networkProfileService.preset(_networkPreset);
    }

    final cached = _currentMeasurement;
    if (cached != null) {
      return _networkProfileService.fromMeasurement(cached);
    }

    if (_isSessionActive(sessionId)) {
      setState(() {
        _backgroundDecodeStatus = 'MEASURING CURRENT CONNECTION';
      });
    }

    try {
      final measurement = await _connectionMeasurementService.measure(
        speedTestUrl: speedTestUrl,
        latencyUrl: latencyTestUrl,
      );

      if (!_isSessionActive(sessionId)) {
        return _networkProfileService.fallbackPreset();
      }

      setState(() {
        _currentMeasurement = measurement;
      });
      return _networkProfileService.fromMeasurement(measurement);
    } catch (e) {
      if (_isSessionActive(sessionId)) {
        setState(() {
          _error =
              'CURRENT CONNECTION MEASUREMENT FAILED. USING STUTTGART TYPICAL.';
        });
      }
      return _networkProfileService.fallbackPreset();
    }
  }

  Future<void> _onPlayPressed() async {
    final assets = _installedAssets;
    if (assets == null || _isPreparing) {
      return;
    }

    await _audioService.stop();
    await _decoderService.resetSession();
    await _sageService.stop();
    await _sameService.stop();

    final sessionId = ++_sessionId;

    setState(() {
      _isPreparing = true;
      _isPlaying = false;
      _isPaused = false;
      _liveElapsed = Duration.zero;
      _startupElapsed = Duration.zero;
      _downloadedBytes = 0;
      _startupDownloadedBytes = 0;
      _simulatedSpeedMbps = 0;
      _error = null;
      _backgroundDecodeStatus =
          _networkPreset == NetworkPreset.currentConnection
          ? 'MEASURING CURRENT CONNECTION'
          : 'PREPARING';
    });

    try {
      final runProfile = await _resolveNetworkProfileForRun(sessionId);
      if (!_isSessionActive(sessionId)) {
        return;
      }

      final simulationSeed = _networkProfileService.deterministicSeedForProfile(
        runProfile,
      );
      final simulator = NetworkSimulator(runProfile, seed: simulationSeed);

      final int transferSizeBytes = switch (_mode) {
        DemoMode.mp3 => assets.mp3SizeBytes,
        DemoMode.neuralSpect => assets.sstSizeBytes,
        DemoMode.neuralSage => assets.sageSizeBytes,
        DemoMode.neuralSameS => assets.sameSizeBytes,
      };
      final int startupThresholdBytes = transferSizeBytes;
      final int maxTransferBytes = transferSizeBytes;

      final startedAt = DateTime.now();
      setState(() {
        _activeRunProfile = runProfile;
        _backgroundDecodeStatus = 'PREPARING';
      });

      while (_isSessionActive(sessionId)) {
        final elapsed = DateTime.now().difference(startedAt);
        final loaded = simulator.loadedBytes(
          elapsed: elapsed,
          maxBytes: maxTransferBytes,
        );
        final simulatedMbps = simulator.currentThroughputMbps(elapsed: elapsed);

        setState(() {
          _liveElapsed = elapsed;
          _downloadedBytes = loaded;
          _simulatedSpeedMbps = simulatedMbps;
        });

        if (loaded >= startupThresholdBytes) {
          break;
        }
        await Future.delayed(const Duration(milliseconds: 40));
      }

      if (!_isSessionActive(sessionId)) {
        return;
      }

      final startupDownloadedBytes = _downloadedBytes;

      if (_mode == DemoMode.mp3) {
        await _audioService.playMp3Asset();
        await _audioService.waitForPlaybackStart();
        if (_isSessionActive(sessionId)) {
          setState(() {
            _backgroundDecodeStatus = 'STREAMING (MP3)';
          });
        }
      } else if (_mode == DemoMode.neuralSpect) {
        final request = _buildNeuralRequest(assets);

        final firstBlock = await _decoderService.startSession(request);
        if (!_isSessionActive(sessionId)) {
          return;
        }

        if (firstBlock.frameCount <= 0 || firstBlock.pcm.isEmpty) {
          throw StateError('NEURAL STREAM RETURNED EMPTY FIRST BLOCK.');
        }

        await _audioService.playNeuralStream(
          firstBlockPcm: firstBlock.pcm,
          sampleRate: firstBlock.sampleRate,
          channels: firstBlock.channels,
        );

        setState(() {
          _backgroundDecodeStatus = firstBlock.decoderReused
              ? 'STREAMING (DECODER REUSED)'
              : 'STREAMING (DECODER LOADED)';
        });

        if (firstBlock.done) {
          _audioService.completeNeuralStream();
        } else {
          unawaited(_pumpNeuralStream(sessionId));
        }

        await _audioService.waitForPlaybackStart();
      } else if (_mode == DemoMode.neuralSage) {
        final firstChunk = await _sageService.start(
          modelPath: assets.sageModelPath,
          sagePath: assets.sagePath,
          threads: _threads,
          cores: _cores,
        );
        if (!_isSessionActive(sessionId)) {
          return;
        }

        if (firstChunk.frameCount <= 0 || firstChunk.pcm.isEmpty) {
          throw StateError('SAGE STREAM RETURNED EMPTY FIRST BLOCK.');
        }

        await _audioService.playNeuralStream(
          firstBlockPcm: firstChunk.pcm,
          sampleRate: firstChunk.sampleRate,
          channels: firstChunk.channels,
        );

        setState(() {
          _backgroundDecodeStatus = firstChunk.decoderReused
              ? 'STREAMING (SAGE REUSED)'
              : 'STREAMING (SAGE LOADED)';
        });

        if (firstChunk.done) {
          _audioService.completeNeuralStream();
        } else {
          unawaited(_pumpSageStream(sessionId));
        }

        await _audioService.waitForPlaybackStart();
      } else {
        final firstChunk = await _sameService.start(
          modelPath: assets.sameModelPath,
          samePath: assets.samePath,
          threads: _threads,
          cores: _cores,
        );
        if (!_isSessionActive(sessionId)) {
          return;
        }

        if (firstChunk.frameCount <= 0 || firstChunk.pcm.isEmpty) {
          throw StateError('SAME-S STREAM RETURNED EMPTY FIRST BLOCK.');
        }

        await _audioService.playNeuralStream(
          firstBlockPcm: firstChunk.pcm,
          sampleRate: firstChunk.sampleRate,
          channels: firstChunk.channels,
        );

        setState(() {
          _backgroundDecodeStatus = firstChunk.decoderReused
              ? 'STREAMING (SAME-S REUSED)'
              : 'STREAMING (SAME-S LOADED)';
        });

        if (firstChunk.done) {
          _audioService.completeNeuralStream();
        } else {
          unawaited(_pumpSameStream(sessionId));
        }

        await _audioService.waitForPlaybackStart();
      }

      if (!_isSessionActive(sessionId)) {
        return;
      }

      final startupElapsed = DateTime.now().difference(startedAt);
      setState(() {
        _startupElapsed = startupElapsed;
        _liveElapsed = startupElapsed;
        _startupDownloadedBytes = startupDownloadedBytes;
        _downloadedBytes = startupDownloadedBytes;
        _isPreparing = false;
        _isPlaying = true;
        _isPaused = false;
      });

      _recordRun(elapsed: startupElapsed, startupBytes: startupDownloadedBytes);
    } catch (e) {
      if (!_isSessionActive(sessionId)) {
        return;
      }
      setState(() {
        _isPreparing = false;
        _isPlaying = false;
        _isPaused = false;
        _error = 'PLAYBACK FAILED: $e';
      });
    }
  }

  Future<void> _onPauseResumePressed() async {
    if (_isPreparing || (!_isPlaying && !_isPaused)) {
      return;
    }

    try {
      if (_isPaused) {
        await _audioService.resume();
        if (!mounted) {
          return;
        }
        setState(() {
          _isPaused = false;
          _isPlaying = true;
          _backgroundDecodeStatus = 'PLAYBACK RESUMED';
        });
      } else {
        await _audioService.pause();
        if (!mounted) {
          return;
        }
        setState(() {
          _isPaused = true;
          _isPlaying = false;
          _backgroundDecodeStatus = 'PLAYBACK PAUSED';
        });
      }
    } catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error = 'PAUSE/RESUME FAILED: $e';
      });
    }
  }

  Future<void> _onStopPressed() async {
    _sessionId += 1;
    await _decoderService.resetSession();
    await _sageService.stop();
    await _sameService.stop();
    await _audioService.stop();
    if (!mounted) {
      return;
    }
    setState(() {
      _isPreparing = false;
      _isPlaying = false;
      _isPaused = false;
      _liveElapsed = Duration.zero;
      _startupElapsed = Duration.zero;
      _downloadedBytes = 0;
      _startupDownloadedBytes = 0;
      _simulatedSpeedMbps = 0;
      _activeRunProfile = null;
      _currentMeasurement = null;
      _error = null;
      _backgroundDecodeStatus = 'IDLE';
    });
  }

  Future<void> _pumpNeuralStream(int sessionId) async {
    int blocksDecoded = 0;

    try {
      while (_isSessionActive(sessionId)) {
        final block = await _decoderService.decodeNextBlock();
        if (!_isSessionActive(sessionId)) {
          return;
        }

        if (block.frameCount > 0 && block.pcm.isNotEmpty) {
          await _audioService.appendNeuralPcm(block.pcm);
          blocksDecoded += 1;
        }

        if (block.done) {
          _audioService.completeNeuralStream();
          if (!_isSessionActive(sessionId)) {
            return;
          }
          setState(() {
            _backgroundDecodeStatus = block.canceled
                ? 'STREAM CANCELED ($blocksDecoded BLOCKS)'
                : 'STREAM DONE ($blocksDecoded BLOCKS)';
          });
          return;
        }

        if (blocksDecoded % 8 == 0 && mounted) {
          setState(() {
            _backgroundDecodeStatus =
                'STREAM ${block.currentBlockIndex + 1}/${block.totalBlocks}';
          });
        }
      }
    } catch (e) {
      await _audioService.abortNeuralStream();
      if (!_isSessionActive(sessionId)) {
        return;
      }
      setState(() {
        _backgroundDecodeStatus = 'STREAM ERROR: $e';
      });
    }
  }

  Future<void> _pumpSageStream(int sessionId) async {
    int chunksDecoded = 0;

    try {
      while (_isSessionActive(sessionId)) {
        final chunk = await _sageService.next();
        if (!_isSessionActive(sessionId)) {
          return;
        }

        if (chunk.frameCount > 0 && chunk.pcm.isNotEmpty) {
          await _audioService.appendNeuralPcm(chunk.pcm);
          chunksDecoded += 1;
        }

        if (chunk.done) {
          _audioService.completeNeuralStream();
          if (!_isSessionActive(sessionId)) {
            return;
          }
          setState(() {
            _backgroundDecodeStatus =
                'STREAM DONE (SAGE, $chunksDecoded CHUNKS)';
          });
          return;
        }

        if (chunksDecoded % 8 == 0 && mounted) {
          setState(() {
            _backgroundDecodeStatus =
                'STREAM SAGE ${chunk.windowsDecoded}/${chunk.windowCount}';
          });
        }
      }
    } catch (e) {
      await _audioService.abortNeuralStream();
      if (!_isSessionActive(sessionId)) {
        return;
      }
      setState(() {
        _backgroundDecodeStatus = 'SAGE STREAM ERROR: $e';
      });
    }
  }

  Future<void> _pumpSameStream(int sessionId) async {
    int chunksDecoded = 0;

    try {
      while (_isSessionActive(sessionId)) {
        final chunk = await _sameService.next();
        if (!_isSessionActive(sessionId)) {
          return;
        }

        if (chunk.frameCount > 0 && chunk.pcm.isNotEmpty) {
          await _audioService.appendNeuralPcm(chunk.pcm);
          chunksDecoded += 1;
        }

        if (chunk.done) {
          _audioService.completeNeuralStream();
          if (!_isSessionActive(sessionId)) {
            return;
          }
          setState(() {
            _backgroundDecodeStatus =
                'STREAM DONE (SAME-S, $chunksDecoded CHUNKS)';
          });
          return;
        }

        if (chunksDecoded % 8 == 0 && mounted) {
          setState(() {
            _backgroundDecodeStatus =
                'STREAM SAME-S ${chunk.windowsDecoded}/${chunk.windowCount}';
          });
        }
      }
    } catch (e) {
      await _audioService.abortNeuralStream();
      if (!_isSessionActive(sessionId)) {
        return;
      }
      setState(() {
        _backgroundDecodeStatus = 'SAME-S STREAM ERROR: $e';
      });
    }
  }

  void _recordRun({required Duration elapsed, required int startupBytes}) {
    final run = RunHistoryEntry(
      mode: _mode,
      networkPreset: _networkPreset,
      modelPreset: _modelPreset,
      threads: _threads,
      cores: _cores,
      elapsed: elapsed,
      startupBytes: startupBytes,
    );

    debugPrint(
      '[run] ${_mode.name} T$_threads C$_cores ${elapsed.inMilliseconds}ms',
    );
    setState(() {
      _recentRuns.add(run);
      if (_recentRuns.length > 40) {
        _recentRuns.removeAt(0);
      }
    });
  }

  Color _timeColor(Duration duration) {
    final s = duration.inMilliseconds / 1000.0;
    if (s < 2.0) {
      return const Color(0xFF00FF66);
    }
    if (s < 3.0) {
      return const Color(0xFFFFFF00);
    }
    if (s < 4.0) {
      return const Color(0xFFFF8A00);
    }
    return const Color(0xFFFF3030);
  }

  String _formatStopwatch(Duration duration) {
    final totalMs = duration.inMilliseconds.clamp(0, 99999999);
    final seconds = totalMs ~/ 1000;
    final millis = totalMs % 1000;
    return '${seconds.toString().padLeft(2, '0')}:${millis.toString().padLeft(3, '0')}';
  }

  int _blocksForBytes(int bytes) {
    if (bytes <= 0) {
      return 0;
    }
    return (bytes + _memoryBlockBytes - 1) ~/ _memoryBlockBytes;
  }

  String _formatKb(int bytes) {
    return '${(bytes / 1024.0).toStringAsFixed(1)} KB';
  }

  String _formatKbCounter(int bytes) {
    return (bytes / 1000.0).toStringAsFixed(1);
  }

  Color _kbCounterColor(DemoMode mode) {
    return mode == DemoMode.mp3
        ? const Color(0xFFFF3030)
        : const Color(0xFF00FF66);
  }

  Widget _buildPixelBlocks({
    required int bytes,
    required Color color,
    required Color overflowTextColor,
  }) {
    const int maxVisibleBlocks = 320;
    final blocks = _blocksForBytes(bytes);
    final visible = blocks > maxVisibleBlocks ? maxVisibleBlocks : blocks;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 3,
          runSpacing: 3,
          children: List<Widget>.generate(
            visible,
            (index) => Container(width: 8, height: 8, color: color),
          ),
        ),
        if (blocks > maxVisibleBlocks) ...[
          const SizedBox(height: 6),
          Text(
            '+${blocks - maxVisibleBlocks} BLOCKS',
            style: TextStyle(
              color: overflowTextColor,
              fontFamily: 'monospace',
              fontSize: 10,
            ),
          ),
        ],
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final isDayStyle = widget.isDayStyle;
    final fg = isDayStyle ? Colors.black : Colors.white;
    final muted = isDayStyle ? Colors.black54 : Colors.white70;
    final errorColor = isDayStyle
        ? const Color(0xFFD32F2F)
        : const Color(0xFFFF5252);
    final primaryButtonBg = isDayStyle ? Colors.black : Colors.white;
    final primaryButtonFg = isDayStyle ? Colors.white : Colors.black;

    final assets = _installedAssets;
    final displayDownloaded = _startupDownloadedBytes > 0
        ? _startupDownloadedBytes
        : _downloadedBytes;
    final displayElapsed = _isPreparing ? _liveElapsed : _startupElapsed;

    final memoryPixelsBytes = _isPreparing
        ? _downloadedBytes
        : displayDownloaded;
    final memoryPixelsTitle = _isPreparing
        ? 'MEMORY PIXELS (LIVE PREPARE)'
        : 'MEMORY PIXELS (CURRENT RUN)';
    final activeProfile =
        _activeRunProfile ?? _networkProfileService.preset(_networkPreset);
    final liveMeasurement = _currentMeasurement;
    final kbCounterBytes = _isPreparing
        ? _downloadedBytes
        : _startupDownloadedBytes;
    final kbCounterTargetBytes = assets == null
        ? 0
        : switch (_mode) {
            DemoMode.mp3 => assets.mp3SizeBytes,
            DemoMode.neuralSpect => assets.sstSizeBytes,
            DemoMode.neuralSage => assets.sageSizeBytes,
            DemoMode.neuralSameS => assets.sameSizeBytes,
          };
    final kbCounterColor = _kbCounterColor(_mode);
    final modelLabel = _mode.modelLabel(_modelPreset);

    return Scaffold(
      body: _loadingAssets
          ? Center(child: CircularProgressIndicator(color: fg))
          : SafeArea(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            'MP3 vs Neural Codecs Startup Time',
                            style: TextStyle(
                              color: fg,
                              fontFamily: 'monospace',
                              fontSize: 13,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 1.0,
                            ),
                          ),
                        ),
                        OutlinedButton(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: fg,
                            side: BorderSide(color: fg, width: 2),
                            shape: const RoundedRectangleBorder(),
                          ),
                          onPressed: _isPreparing ? null : _openSettings,
                          child: const Text(
                            'SETTINGS',
                            style: TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        OutlinedButton(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: fg,
                            side: BorderSide(color: fg, width: 2),
                            shape: const RoundedRectangleBorder(),
                          ),
                          onPressed: _isPreparing ? null : widget.onToggleTheme,
                          child: Text(
                            isDayStyle ? 'NIGHT' : 'DAY',
                            style: const TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        OutlinedButton(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: fg,
                            side: BorderSide(color: fg, width: 2),
                            shape: const RoundedRectangleBorder(),
                          ),
                          onPressed: _openHistory,
                          child: const Text(
                            'HISTORY',
                            style: TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 18),
                    Text(
                      'TIME TO PLAYBACK',
                      style: TextStyle(
                        color: muted,
                        fontFamily: 'monospace',
                        fontSize: 11,
                        letterSpacing: 1.4,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _formatStopwatch(displayElapsed),
                      style: TextStyle(
                        color: _timeColor(displayElapsed),
                        fontFamily: 'monospace',
                        fontSize: 64,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 3,
                        height: 1,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'MEMORY AT START: ${_formatKb(displayDownloaded)} (${_blocksForBytes(displayDownloaded)} BLOCKS)',
                      style: TextStyle(
                        color: fg,
                        fontFamily: 'monospace',
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: primaryButtonFg,
                              backgroundColor: primaryButtonBg,
                              side: BorderSide(color: fg, width: 2),
                              shape: const RoundedRectangleBorder(),
                              padding: const EdgeInsets.symmetric(vertical: 16),
                            ),
                            onPressed: (_loadingAssets || _isPreparing)
                                ? null
                                : _onPlayPressed,
                            child: Text(
                              _isPreparing ? 'PREPARING...' : 'PLAY',
                              style: const TextStyle(
                                fontFamily: 'monospace',
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.4,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: OutlinedButton(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: fg,
                              side: BorderSide(color: fg, width: 2),
                              shape: const RoundedRectangleBorder(),
                              padding: const EdgeInsets.symmetric(vertical: 16),
                            ),
                            onPressed:
                                (_isPreparing || (!_isPlaying && !_isPaused))
                                ? null
                                : _onPauseResumePressed,
                            child: Text(
                              _isPaused ? 'RESUME' : 'PAUSE',
                              style: const TextStyle(
                                fontFamily: 'monospace',
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.4,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: OutlinedButton(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: fg,
                              side: BorderSide(color: fg, width: 2),
                              shape: const RoundedRectangleBorder(),
                              padding: const EdgeInsets.symmetric(vertical: 16),
                            ),
                            onPressed: (_isPreparing || _isPlaying || _isPaused)
                                ? _onStopPressed
                                : null,
                            child: const Text(
                              'STOP',
                              style: TextStyle(
                                fontFamily: 'monospace',
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.4,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Text(
                      'MODE ${_mode.label.toUpperCase()} • NET ${activeProfile.label.toUpperCase()} • $modelLabel • T$_threads • C$_cores',
                      style: TextStyle(
                        color: muted,
                        fontFamily: 'monospace',
                        fontSize: 10,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'SOURCE: ${activeProfile.source} • SIM SPEED ${_simulatedSpeedMbps.toStringAsFixed(1)} Mbps',
                      style: TextStyle(
                        color: muted,
                        fontFamily: 'monospace',
                        fontSize: 10,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'STATUS: $_backgroundDecodeStatus',
                      style: TextStyle(
                        color: fg,
                        fontFamily: 'monospace',
                        fontSize: 11,
                      ),
                    ),
                    if (_networkPreset == NetworkPreset.currentConnection &&
                        liveMeasurement != null) ...[
                      const SizedBox(height: 8),
                      Text(
                        'Transport: ${liveMeasurement.transport.label}',
                        style: TextStyle(
                          color: fg,
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                      Text(
                        'Measured download: ${liveMeasurement.averageThroughputMbps.toStringAsFixed(1)} Mbps',
                        style: TextStyle(
                          color: fg,
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                      Text(
                        'Median ping: ${liveMeasurement.medianRttMs} ms',
                        style: TextStyle(
                          color: fg,
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                      Text(
                        'Simulation speed: ${activeProfile.downloadMbps.toStringAsFixed(1)} Mbps',
                        style: TextStyle(
                          color: fg,
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                    ],
                    if (_error != null) ...[
                      const SizedBox(height: 8),
                      Text(
                        _error!,
                        style: TextStyle(
                          color: errorColor,
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    if (assets != null) ...[
                      Text(
                        memoryPixelsTitle,
                        style: TextStyle(
                          color: muted,
                          fontFamily: 'monospace',
                          fontSize: 11,
                          letterSpacing: 1.2,
                        ),
                      ),
                      const SizedBox(height: 8),
                      _buildPixelBlocks(
                        bytes: memoryPixelsBytes,
                        color: fg,
                        overflowTextColor: muted,
                      ),
                      const SizedBox(height: 20),
                      Text(
                        'LOADING COUNTER',
                        style: TextStyle(
                          color: muted,
                          fontFamily: 'monospace',
                          fontSize: 11,
                          letterSpacing: 1.2,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${_formatKbCounter(kbCounterBytes)} KB',
                        style: TextStyle(
                          color: kbCounterColor,
                          fontFamily: 'monospace',
                          fontSize: 54,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 2,
                          height: 1,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'TARGET ${_formatKbCounter(kbCounterTargetBytes)} KB',
                        style: TextStyle(
                          color: muted,
                          fontFamily: 'monospace',
                          fontSize: 11,
                          letterSpacing: 1.1,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
    );
  }
}
