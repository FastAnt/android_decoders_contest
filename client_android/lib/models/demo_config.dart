enum DemoMode { mp3, neuralSpect, neuralSage }

extension DemoModeLabel on DemoMode {
  String get label {
    switch (this) {
      case DemoMode.mp3:
        return 'MP3';
      case DemoMode.neuralSpect:
        return 'NEURAL SPECT';
      case DemoMode.neuralSage:
        return 'NEURAL SAGE';
    }
  }
}

enum NetworkPreset {
  stuttgartPoor,
  stuttgartTypical,
  stuttgartGood,
  currentConnection,
}

class NetworkProfileSource {
  static const String preset = 'Preset profile';
  static const String liveMeasurement = 'Live measurement';
  static const String stuttgartDataset = 'Measured Stuttgart dataset';
}

class NetworkProfile {
  const NetworkProfile({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.label,
    required this.downloadMbps,
    required this.pingMs,
    required this.variation,
    required this.source,
  });

  final String id;
  final String title;
  final String subtitle;
  final String label;
  final double downloadMbps;
  final int pingMs;
  final double variation;
  final String source;

  double get throughputBytesPerSecond => downloadMbps * 1000 * 1000 / 8.0;
}

const Map<NetworkPreset, NetworkProfile> kNetworkProfiles = {
  NetworkPreset.stuttgartPoor: NetworkProfile(
    id: 'stuttgart-poor',
    title: 'Stuttgart Poor',
    subtitle: 'Poor - 3G-like / weak mobile',
    label: 'Poor',
    downloadMbps: 0.8,
    pingMs: 180,
    variation: 0.35,
    source: NetworkProfileSource.preset,
  ),
  NetworkPreset.stuttgartTypical: NetworkProfile(
    id: 'stuttgart-typical',
    title: 'Stuttgart Typical',
    subtitle: 'Typical - typical 4G',
    label: 'Typical',
    downloadMbps: 6.0,
    pingMs: 70,
    variation: 0.25,
    source: NetworkProfileSource.preset,
  ),
  NetworkPreset.stuttgartGood: NetworkProfile(
    id: 'stuttgart-good',
    title: 'Stuttgart Good',
    subtitle: 'Good - good 5G',
    label: 'Good',
    downloadMbps: 35.0,
    pingMs: 30,
    variation: 0.20,
    source: NetworkProfileSource.preset,
  ),
  NetworkPreset.currentConnection: NetworkProfile(
    id: 'current-connection',
    title: 'Current Connection',
    subtitle: 'Current - live measured',
    label: 'Current',
    downloadMbps: 6.0,
    pingMs: 70,
    variation: 0.25,
    source: NetworkProfileSource.liveMeasurement,
  ),
};

enum NeuralModelPreset { f25Fp32, f25Fp16, f75Fp32, f75Fp16, f100Fp16 }

class NeuralModelConfig {
  const NeuralModelConfig({
    required this.label,
    required this.assetFileName,
    required this.description,
  });

  final String label;
  final String assetFileName;
  final String description;
}

const Map<NeuralModelPreset, NeuralModelConfig> kNeuralModels = {
  NeuralModelPreset.f25Fp32: NeuralModelConfig(
    label: 'f25 FP32',
    assetFileName: 'spectrostream_decoder_core_fp32_f25.tflite',
    description:
        'Fast baseline. RTF 0.79 on Galaxy S24 (6 threads). Boundary artifacts possible.',
  ),
  NeuralModelPreset.f25Fp16: NeuralModelConfig(
    label: 'f25 FP16',
    assetFileName: 'spectrostream_decoder_core_fp16_f25.tflite',
    description:
        '68 MB model. Experimental; on-device speed is pending measurement.',
  ),
  NeuralModelPreset.f75Fp32: NeuralModelConfig(
    label: 'f75 FP32',
    assetFileName: 'spectrostream_decoder_core_fp32_f75.tflite',
    description:
        'Context-aware mode without boundary artifacts. Slower (RTF 2.59 on S24).',
  ),
  NeuralModelPreset.f75Fp16: NeuralModelConfig(
    label: 'f75 FP16',
    assetFileName: 'spectrostream_decoder_core_fp16_f75.tflite',
    description:
        'Context-aware FP16 model. Expected lower memory use than f75 FP32.',
  ),
  NeuralModelPreset.f100Fp16: NeuralModelConfig(
    label: 'f100 FP16',
    assetFileName: 'spectrostream_decoder_core_fp16_f100.tflite',
    description: 'Largest FP16 context model for quality-focused evaluation.',
  ),
};

class DemoDefaults {
  static const network = NetworkPreset.stuttgartTypical;
  static const mode = DemoMode.neuralSpect;
  static const model = NeuralModelPreset.f25Fp32;
  static const threads = 6;
  static const cores = 8;
}
