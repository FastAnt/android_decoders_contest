import 'package:flutter_test/flutter_test.dart';

import 'package:client_android/models/demo_config.dart';

void main() {
  test('SAME-S mode has a label and a fixed model name', () {
    expect(DemoMode.values, contains(DemoMode.neuralSameS));
    expect(DemoMode.neuralSameS.label, 'NEURAL SAME-S');
    expect(
      DemoMode.neuralSameS.modelLabel(NeuralModelPreset.f25Fp32),
      'SAME-S R128',
    );
  });
}
