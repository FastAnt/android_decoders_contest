import '../models/demo_config.dart';

class NetworkSimulator {
  const NetworkSimulator(this.profile, {required this.seed});

  final NetworkProfile profile;
  final int seed;

  static const int _stepMs = 250;

  int loadedBytes({required Duration elapsed, int? maxBytes}) {
    final payloadTimeMs = elapsed.inMilliseconds - profile.pingMs;
    if (payloadTimeMs <= 0) {
      return 0;
    }

    int rawBytes = 0;
    int fullSteps = payloadTimeMs ~/ _stepMs;
    int remainderMs = payloadTimeMs % _stepMs;

    for (int step = 0; step < fullSteps; step++) {
      final throughputBps = _throughputBytesPerSecondAt(step);
      rawBytes += (throughputBps * (_stepMs / 1000.0)).round();
    }

    if (remainderMs > 0) {
      final throughputBps = _throughputBytesPerSecondAt(fullSteps);
      rawBytes += (throughputBps * (remainderMs / 1000.0)).round();
    }

    if (maxBytes == null) {
      return rawBytes;
    }
    return rawBytes > maxBytes ? maxBytes : rawBytes;
  }

  double currentThroughputMbps({required Duration elapsed}) {
    final payloadTimeMs = elapsed.inMilliseconds - profile.pingMs;
    if (payloadTimeMs <= 0) {
      return 0.0;
    }
    final step = payloadTimeMs ~/ _stepMs;
    final bps = _throughputBytesPerSecondAt(step);
    return (bps * 8.0) / (1000.0 * 1000.0);
  }

  Duration timeToLoadBytes(int bytes) {
    if (bytes <= 0) {
      return Duration(milliseconds: profile.pingMs);
    }
    final payloadSeconds = bytes / profile.throughputBytesPerSecond;
    final totalMs = profile.pingMs + (payloadSeconds * 1000).ceil();
    return Duration(milliseconds: totalMs);
  }

  double _throughputBytesPerSecondAt(int step) {
    final base = profile.throughputBytesPerSecond;
    if (base <= 0) {
      return 0;
    }

    final noiseA = _unitNoise(seed ^ (step * 1013));
    final noiseB = _unitNoise(seed ^ (step * 2179 + 17));
    final combined = ((noiseA * 0.7) + (noiseB * 0.3)) * 2.0 - 1.0;

    final variation = profile.variation.clamp(0.0, 0.95);
    final multiplier = (1.0 + combined * variation).clamp(0.15, 3.0);
    return base * multiplier;
  }

  double _unitNoise(int value) {
    int x = value & 0x7fffffff;
    x = (x ^ 61) ^ (x >> 16);
    x = (x + (x << 3)) & 0x7fffffff;
    x = x ^ (x >> 4);
    x = (x * 0x27d4eb2d) & 0x7fffffff;
    x = x ^ (x >> 15);
    return (x & 0x7fffffff) / 0x7fffffff;
  }
}
