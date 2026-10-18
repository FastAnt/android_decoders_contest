import 'package:flutter/material.dart';

import '../models/demo_config.dart';

class DemoSettingsResult {
  const DemoSettingsResult({
    required this.mode,
    required this.networkPreset,
    required this.modelPreset,
    required this.threads,
    required this.cores,
  });

  final DemoMode mode;
  final NetworkPreset networkPreset;
  final NeuralModelPreset modelPreset;
  final int threads;
  final int cores;
}

class DemoSettingsScreen extends StatefulWidget {
  const DemoSettingsScreen({
    super.key,
    required this.initialMode,
    required this.initialNetworkPreset,
    required this.initialModelPreset,
    required this.initialThreads,
    required this.initialCores,
  });

  final DemoMode initialMode;
  final NetworkPreset initialNetworkPreset;
  final NeuralModelPreset initialModelPreset;
  final int initialThreads;
  final int initialCores;

  @override
  State<DemoSettingsScreen> createState() => _DemoSettingsScreenState();
}

class _DemoSettingsScreenState extends State<DemoSettingsScreen> {
  late DemoMode _mode;
  late NetworkPreset _networkPreset;
  late NeuralModelPreset _modelPreset;
  late int _threads;
  late int _cores;

  @override
  void initState() {
    super.initState();
    _mode = widget.initialMode;
    _networkPreset = widget.initialNetworkPreset;
    _modelPreset = widget.initialModelPreset;
    _threads = widget.initialThreads;
    _cores = widget.initialCores;
  }

  @override
  Widget build(BuildContext context) {
    final isDayStyle = Theme.of(context).brightness == Brightness.light;
    final fg = isDayStyle ? Colors.black : Colors.white;
    final muted = isDayStyle ? Colors.black54 : Colors.white70;
    final selectedBg = isDayStyle ? Colors.black : Colors.white;
    final selectedFg = isDayStyle ? Colors.white : Colors.black;
    final unselectedBg = isDayStyle ? Colors.white : Colors.black;

    return Scaffold(
      appBar: AppBar(title: const Text('SETTINGS'), centerTitle: false),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 240),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _SectionLabel('MODE', color: fg),
              const SizedBox(height: 8),
              _OptionWrap<DemoMode>(
                values: DemoMode.values,
                selected: _mode,
                labelBuilder: (mode) {
                  switch (mode) {
                    case DemoMode.mp3:
                      return 'MP3';
                    case DemoMode.neuralSpect:
                      return 'NEURAL SPECT';
                    case DemoMode.neuralSage:
                      return 'NEURAL SAGE';
                  }
                },
                onSelected: (mode) => setState(() => _mode = mode),
                borderColor: fg,
                selectedBackground: selectedBg,
                selectedForeground: selectedFg,
                unselectedBackground: unselectedBg,
                unselectedForeground: fg,
              ),
              const SizedBox(height: 20),
              _SectionLabel('NETWORK', color: fg),
              const SizedBox(height: 8),
              _OptionWrap<NetworkPreset>(
                values: NetworkPreset.values,
                selected: _networkPreset,
                labelBuilder: (preset) {
                  switch (preset) {
                    case NetworkPreset.stuttgartPoor:
                      return 'STUTTGART POOR';
                    case NetworkPreset.stuttgartTypical:
                      return 'STUTTGART TYPICAL';
                    case NetworkPreset.stuttgartGood:
                      return 'STUTTGART GOOD';
                    case NetworkPreset.currentConnection:
                      return 'CURRENT CONNECTION';
                  }
                },
                onSelected: (preset) => setState(() => _networkPreset = preset),
                borderColor: fg,
                selectedBackground: selectedBg,
                selectedForeground: selectedFg,
                unselectedBackground: unselectedBg,
                unselectedForeground: fg,
              ),
              const SizedBox(height: 8),
              Text(
                'Poor      - 3G-like / weak mobile\n'
                'Typical   - typical 4G\n'
                'Good      - good 5G\n'
                'Current   - live measured',
                style: TextStyle(
                  color: muted,
                  fontFamily: 'monospace',
                  fontSize: 10,
                  height: 1.6,
                ),
              ),
              const SizedBox(height: 20),
              _SectionLabel('MODEL', color: fg),
              const SizedBox(height: 8),
              _OptionWrap<NeuralModelPreset>(
                values: NeuralModelPreset.values,
                selected: _modelPreset,
                labelBuilder: (preset) =>
                    kNeuralModels[preset]!.label.toUpperCase(),
                onSelected: (preset) => setState(() => _modelPreset = preset),
                borderColor: fg,
                selectedBackground: selectedBg,
                selectedForeground: selectedFg,
                unselectedBackground: unselectedBg,
                unselectedForeground: fg,
              ),
              const SizedBox(height: 20),
              _SectionLabel('THREADS', color: fg),
              const SizedBox(height: 8),
              _OptionWrap<int>(
                values: const [1, 2, 4, 6, 8],
                selected: _threads,
                labelBuilder: (value) => '$value',
                onSelected: (value) => setState(() => _threads = value),
                borderColor: fg,
                selectedBackground: selectedBg,
                selectedForeground: selectedFg,
                unselectedBackground: unselectedBg,
                unselectedForeground: fg,
              ),
              const SizedBox(height: 20),
              _SectionLabel('CORES', color: fg),
              const SizedBox(height: 8),
              _OptionWrap<int>(
                values: const [1, 2, 4, 6, 8],
                selected: _cores,
                labelBuilder: (value) => '$value',
                onSelected: (value) => setState(() => _cores = value),
                borderColor: fg,
                selectedBackground: selectedBg,
                selectedForeground: selectedFg,
                unselectedBackground: unselectedBg,
                unselectedForeground: fg,
              ),
              const SizedBox(height: 24),
              Text(
                'Pixel demo preset editor\nfor slide-ready A/B launches',
                style: TextStyle(
                  color: muted,
                  fontFamily: 'monospace',
                  fontSize: 11,
                  height: 1.5,
                ),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: selectedFg,
                    backgroundColor: selectedBg,
                    side: BorderSide(color: fg, width: 2),
                    shape: const RoundedRectangleBorder(),
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  onPressed: () {
                    Navigator.of(context).pop(
                      DemoSettingsResult(
                        mode: _mode,
                        networkPreset: _networkPreset,
                        modelPreset: _modelPreset,
                        threads: _threads,
                        cores: _cores,
                      ),
                    );
                  },
                  child: const Text(
                    'APPLY',
                    style: TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.4,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text, {required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: TextStyle(
        color: color,
        fontFamily: 'monospace',
        fontSize: 12,
        fontWeight: FontWeight.w700,
        letterSpacing: 1.2,
      ),
    );
  }
}

class _OptionWrap<T> extends StatelessWidget {
  const _OptionWrap({
    required this.values,
    required this.selected,
    required this.labelBuilder,
    required this.onSelected,
    required this.borderColor,
    required this.selectedBackground,
    required this.selectedForeground,
    required this.unselectedBackground,
    required this.unselectedForeground,
  });

  final List<T> values;
  final T selected;
  final String Function(T value) labelBuilder;
  final ValueChanged<T> onSelected;
  final Color borderColor;
  final Color selectedBackground;
  final Color selectedForeground;
  final Color unselectedBackground;
  final Color unselectedForeground;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: values
          .map((value) {
            final isSelected = value == selected;
            return InkWell(
              onTap: () => onSelected(value),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 120),
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
                decoration: BoxDecoration(
                  color: isSelected ? selectedBackground : unselectedBackground,
                  border: Border.all(color: borderColor, width: 2),
                ),
                child: Text(
                  labelBuilder(value),
                  style: TextStyle(
                    color: isSelected
                        ? selectedForeground
                        : unselectedForeground,
                    fontFamily: 'monospace',
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.0,
                  ),
                ),
              ),
            );
          })
          .toList(growable: false),
    );
  }
}
