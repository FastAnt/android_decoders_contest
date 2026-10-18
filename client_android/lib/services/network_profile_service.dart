import '../models/demo_config.dart';
import 'connection_measurement_service.dart';

const String speedTestUrl = 'https://speed.cloudflare.com/__down?bytes=5000000';
const String latencyTestUrl = 'https://speed.cloudflare.com/cdn-cgi/trace';

class NetworkProfileService {
  const NetworkProfileService();

  NetworkProfile preset(NetworkPreset preset) {
    final profile = kNetworkProfiles[preset];
    if (profile == null) {
      return kNetworkProfiles[NetworkPreset.stuttgartTypical]!;
    }
    return profile;
  }

  NetworkProfile fallbackPreset() {
    return kNetworkProfiles[NetworkPreset.stuttgartTypical]!;
  }

  NetworkProfile fromMeasurement(ConnectionMeasurementResult measurement) {
    return NetworkProfile(
      id: 'current-live',
      title: 'Current Connection',
      subtitle: 'Current - live measured',
      label: 'Current',
      downloadMbps: measurement.conservativeThroughputMbps,
      pingMs: measurement.medianRttMs,
      variation: 0.18,
      source: NetworkProfileSource.liveMeasurement,
    );
  }

  String subtitleFor(NetworkPreset preset) {
    switch (preset) {
      case NetworkPreset.stuttgartPoor:
        return 'Poor - 3G-like / weak mobile';
      case NetworkPreset.stuttgartTypical:
        return 'Typical - typical 4G';
      case NetworkPreset.stuttgartGood:
        return 'Good - good 5G';
      case NetworkPreset.currentConnection:
        return 'Current - live measured';
    }
  }

  String shortLabelFor(NetworkPreset preset) {
    switch (preset) {
      case NetworkPreset.stuttgartPoor:
        return 'Poor';
      case NetworkPreset.stuttgartTypical:
        return 'Typical';
      case NetworkPreset.stuttgartGood:
        return 'Good';
      case NetworkPreset.currentConnection:
        return 'Current';
    }
  }

  int deterministicSeedForProfile(NetworkProfile profile) {
    final input =
        '${profile.id}|${profile.downloadMbps.toStringAsFixed(3)}|${profile.pingMs}|${profile.variation.toStringAsFixed(3)}';
    int hash = 2166136261;
    for (final code in input.codeUnits) {
      hash ^= code;
      hash = (hash * 16777619) & 0x7fffffff;
    }
    return hash;
  }
}
