import 'dart:async';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';

enum ConnectionTransport { cellular, wifi, vpn, unknown }

extension ConnectionTransportLabel on ConnectionTransport {
  String get label {
    switch (this) {
      case ConnectionTransport.cellular:
        return 'Cellular';
      case ConnectionTransport.wifi:
        return 'Wi-Fi';
      case ConnectionTransport.vpn:
        return 'VPN';
      case ConnectionTransport.unknown:
        return 'Unknown';
    }
  }
}

class ConnectionMeasurementResult {
  const ConnectionMeasurementResult({
    required this.transport,
    required this.medianRttMs,
    required this.averageThroughputMbps,
    required this.conservativeThroughputMbps,
    required this.downloadedBytes,
    required this.rttSamples,
  });

  final ConnectionTransport transport;
  final int medianRttMs;
  final double averageThroughputMbps;
  final double conservativeThroughputMbps;
  final int downloadedBytes;
  final int rttSamples;
}

class ConnectionMeasurementException implements Exception {
  const ConnectionMeasurementException(this.message);

  final String message;

  @override
  String toString() => message;
}

class ConnectionMeasurementService {
  const ConnectionMeasurementService();

  static const Duration _requestTimeout = Duration(seconds: 12);

  Future<ConnectionMeasurementResult> measure({
    required String speedTestUrl,
    String? latencyUrl,
    int latencySamples = 4,
  }) async {
    final transport = await _detectTransport();
    final latencyTarget = latencyUrl ?? speedTestUrl;

    final rtts = <int>[];
    for (int i = 0; i < latencySamples; i++) {
      final rtt = await _measureLatencyMs(latencyTarget);
      if (rtt != null) {
        rtts.add(rtt);
      }
      await Future<void>.delayed(const Duration(milliseconds: 120));
    }

    if (rtts.length < 2) {
      throw const ConnectionMeasurementException(
        'Unable to measure latency reliably. Please try Stuttgart Typical.',
      );
    }

    final download = await _measureDownload(speedTestUrl);
    if (download.bytes <= 0 || download.averageMbps <= 0) {
      throw const ConnectionMeasurementException(
        'Download speed test failed. Please use Stuttgart Typical.',
      );
    }

    final conservativeMbps =
        _percentile(download.windowMbps, 0.25) ?? (download.averageMbps * 0.85);

    return ConnectionMeasurementResult(
      transport: transport,
      medianRttMs: _median(rtts),
      averageThroughputMbps: download.averageMbps,
      conservativeThroughputMbps: conservativeMbps.clamp(0.3, 500.0),
      downloadedBytes: download.bytes,
      rttSamples: rtts.length,
    );
  }

  Future<ConnectionTransport> _detectTransport() async {
    try {
      final results = await Connectivity().checkConnectivity();
      if (results.contains(ConnectivityResult.mobile)) {
        return ConnectionTransport.cellular;
      }
      if (results.contains(ConnectivityResult.wifi)) {
        return ConnectionTransport.wifi;
      }
      if (results.contains(ConnectivityResult.vpn)) {
        return ConnectionTransport.vpn;
      }
      return ConnectionTransport.unknown;
    } catch (_) {
      return ConnectionTransport.unknown;
    }
  }

  Future<int?> _measureLatencyMs(String url) async {
    final client = HttpClient()..connectionTimeout = _requestTimeout;
    try {
      final uri = Uri.parse(url);
      final sw = Stopwatch()..start();
      final request = await client.getUrl(uri).timeout(_requestTimeout);
      request.headers.set(HttpHeaders.rangeHeader, 'bytes=0-0');
      request.headers.set(HttpHeaders.acceptEncodingHeader, 'identity');
      final response = await request.close().timeout(_requestTimeout);
      await response.drain<void>();
      sw.stop();

      if (response.statusCode < 200 || response.statusCode >= 400) {
        return null;
      }
      return sw.elapsedMilliseconds;
    } catch (_) {
      return null;
    } finally {
      client.close(force: true);
    }
  }

  Future<_DownloadMeasurement> _measureDownload(String url) async {
    final client = HttpClient()..connectionTimeout = _requestTimeout;
    try {
      final uri = Uri.parse(url);
      final request = await client.getUrl(uri).timeout(_requestTimeout);
      request.headers.set(HttpHeaders.acceptEncodingHeader, 'identity');
      final response = await request.close().timeout(_requestTimeout);

      if (response.statusCode < 200 || response.statusCode >= 400) {
        throw ConnectionMeasurementException(
          'Speed test endpoint returned HTTP ${response.statusCode}.',
        );
      }

      final totalSw = Stopwatch()..start();
      final windowSw = Stopwatch()..start();
      int bytes = 0;
      int windowBytes = 0;
      final windowMbps = <double>[];

      await for (final chunk in response) {
        bytes += chunk.length;
        windowBytes += chunk.length;

        final windowSec = windowSw.elapsedMicroseconds / 1e6;
        if (windowSec >= 0.35) {
          windowMbps.add(_bytesToMbps(windowBytes, windowSec));
          windowSw
            ..reset()
            ..start();
          windowBytes = 0;
        }
      }

      totalSw.stop();
      final totalSec = totalSw.elapsedMicroseconds / 1e6;
      if (windowBytes > 0) {
        final sec = windowSw.elapsedMicroseconds / 1e6;
        if (sec > 0.01) {
          windowMbps.add(_bytesToMbps(windowBytes, sec));
        }
      }

      if (bytes <= 0 || totalSec <= 0) {
        throw const ConnectionMeasurementException(
          'Downloaded 0 bytes during speed test.',
        );
      }

      return _DownloadMeasurement(
        bytes: bytes,
        averageMbps: _bytesToMbps(bytes, totalSec),
        windowMbps: windowMbps,
      );
    } on TimeoutException {
      throw const ConnectionMeasurementException(
        'Connection measurement timed out. Please use Stuttgart Typical.',
      );
    } on SocketException {
      throw const ConnectionMeasurementException(
        'Network unavailable for live measurement. Please use Stuttgart Typical.',
      );
    } finally {
      client.close(force: true);
    }
  }

  double _bytesToMbps(int bytes, double seconds) {
    if (seconds <= 0) {
      return 0;
    }
    return (bytes * 8.0) / (seconds * 1000 * 1000);
  }

  int _median(List<int> values) {
    final sorted = List<int>.from(values)..sort();
    final mid = sorted.length ~/ 2;
    if (sorted.length.isOdd) {
      return sorted[mid];
    }
    return ((sorted[mid - 1] + sorted[mid]) / 2).round();
  }

  double? _percentile(List<double> values, double p) {
    if (values.isEmpty) {
      return null;
    }
    final sorted = List<double>.from(values)..sort();
    final index = ((sorted.length - 1) * p).round();
    return sorted[index.clamp(0, sorted.length - 1)];
  }
}

class _DownloadMeasurement {
  const _DownloadMeasurement({
    required this.bytes,
    required this.averageMbps,
    required this.windowMbps,
  });

  final int bytes;
  final double averageMbps;
  final List<double> windowMbps;
}
