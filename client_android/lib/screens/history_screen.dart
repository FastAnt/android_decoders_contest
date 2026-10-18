import 'package:flutter/material.dart';

import '../models/demo_config.dart';

class RunHistoryEntry {
  const RunHistoryEntry({
    required this.mode,
    required this.networkPreset,
    required this.modelPreset,
    required this.threads,
    required this.cores,
    required this.elapsed,
    required this.startupBytes,
  });

  final DemoMode mode;
  final NetworkPreset networkPreset;
  final NeuralModelPreset modelPreset;
  final int threads;
  final int cores;
  final Duration elapsed;
  final int startupBytes;
}

class HistoryScreen extends StatelessWidget {
  const HistoryScreen({
    super.key,
    required this.runs,
    required this.memoryBlockBytes,
  });

  final List<RunHistoryEntry> runs;
  final int memoryBlockBytes;

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
    return (bytes + memoryBlockBytes - 1) ~/ memoryBlockBytes;
  }

  String _formatKb(int bytes) {
    return '${(bytes / 1024.0).toStringAsFixed(1)} KB';
  }

  Widget _buildPixelBlocks(
    int bytes, {
    required Color blockColor,
    required Color hintColor,
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
            (index) => Container(width: 8, height: 8, color: blockColor),
          ),
        ),
        if (blocks > maxVisibleBlocks) ...[
          const SizedBox(height: 6),
          Text(
            '+${blocks - maxVisibleBlocks} BLOCKS',
            style: TextStyle(
              color: hintColor,
              fontFamily: 'monospace',
              fontSize: 10,
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildRunCard(
    int indexFromLatest,
    RunHistoryEntry run, {
    required Color fg,
    required Color muted,
    required Color border,
  }) {
    final blockCount = _blocksForBytes(run.startupBytes);

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(border: Border.all(color: border, width: 2)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'RUN -$indexFromLatest',
            style: TextStyle(
              color: fg,
              fontFamily: 'monospace',
              fontWeight: FontWeight.w700,
              fontSize: 11,
              letterSpacing: 1.0,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            _formatStopwatch(run.elapsed),
            style: TextStyle(
              color: _timeColor(run.elapsed),
              fontFamily: 'monospace',
              fontSize: 32,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.4,
              height: 1,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '${run.mode.label.toUpperCase()} • ${kNetworkProfiles[run.networkPreset]!.label} • ${run.mode == DemoMode.neuralSage ? 'SAGE R128' : kNeuralModels[run.modelPreset]!.label.toUpperCase()} • T${run.threads} • C${run.cores}',
            style: TextStyle(
              color: muted,
              fontFamily: 'monospace',
              fontSize: 10,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '${_formatKb(run.startupBytes)} • $blockCount BLK',
            style: TextStyle(color: fg, fontFamily: 'monospace', fontSize: 11),
          ),
          const SizedBox(height: 8),
          _buildPixelBlocks(run.startupBytes, blockColor: fg, hintColor: muted),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final orderedRuns = runs.reversed.toList(growable: false);
    final isDayStyle = Theme.of(context).brightness == Brightness.light;
    final fg = isDayStyle ? Colors.black : Colors.white;
    final muted = isDayStyle ? Colors.black54 : Colors.white54;
    final border = isDayStyle ? Colors.black : Colors.white;

    return Scaffold(
      appBar: AppBar(title: const Text('HISTORY'), centerTitle: false),
      body: orderedRuns.isEmpty
          ? Center(
              child: Text(
                'NO RUNS YET',
                style: TextStyle(
                  color: muted,
                  fontFamily: 'monospace',
                  fontSize: 14,
                ),
              ),
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: orderedRuns.length,
              itemBuilder: (context, index) {
                return _buildRunCard(
                  index + 1,
                  orderedRuns[index],
                  fg: fg,
                  muted: muted,
                  border: border,
                );
              },
            ),
    );
  }
}
