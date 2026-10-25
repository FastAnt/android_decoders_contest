# Decode 4 s of audio on 1 core / 2 threads

This is the configuration requested for the presentation:

- **2 worker threads** (`THREADS = 2`);
- **pinned to 1 CPU** (`CORES = 1`);
- app already running, network payload already loaded, decoder warm;
- no app launch, no network wait, no player start in the numbers below.

`T1/C1` in the earlier matrix was 1 thread on 1 core, and `T2/C2` was 2 threads
on 2 cores. The configuration here is **T2/C1: 2 threads sharing one core**.
It was measured separately with decoder-level logs.

## Result

| Codec | 4 s decoded in (2 runs) | Average | Speed vs real time |
|---|---:|---:|---:|
| **SAME-S** r128 W8A8 | 0.639 / 0.584 s | **0.611 s** | **6.5× faster** |
| **SAGE** r128 W8A8 | 1.421 / 1.237 s | **1.329 s** | **3.0× faster** |
| **SpectroStream** f25 FP32 | 5.954 / 6.131 s | **6.043 s** | **0.66× — slower than real time** |

![Decode 4 s on 1 core / 2 threads](images/codec-4s-speed-2t1c.png)

## Slide takeaways

- **SAME-S is the fastest:** 4 s of audio in **~0.61 s**, about **6.5× realtime**.
- **SAGE is second:** **~1.33 s**, about **3.0× realtime**; SAME-S is ~2.2×
  faster than SAGE.
- **SpectroStream is slower than realtime in this configuration:** 4 s takes
  **~6.0 s**, i.e. **0.66× realtime**, so it cannot sustain 4 s of playback on
  one core with two threads. It needs more cores/threads.

In one sentence:

> On one core with two threads, SAME-S decodes 4 s in ~0.6 s (6.5× realtime),
> SAGE in ~1.3 s (3× realtime), and SpectroStream in ~6.0 s — slower than
> realtime.

## Why the numbers are not proportional

- **SAME-S** decodes one 11.15 s window; 4 s fits in one window, but the whole
  window is computed: **~0.61 s**.
- **SAGE** uses 2.97 s core windows; 4 s needs **two** windows, so it computes
  about 5.94 s of audio: **~1.33 s**.
- **SpectroStream** uses 1 s blocks; 4 s needs **four** blocks: **~6.04 s**.

This is a window-granularity effect, not a bitrate or quality comparison.

## Measurement notes

- Device: Samsung Galaxy S25 (`SM-S931B`), Android 15, debug Flutter build.
- Instrumented build logs each decoder window/block time; values are sums of
  the windows needed for 4 s.
- SAME-S/SAGE window times include latent dequantization/container read and
  model inference; SpectroStream includes native block decode and iSTFT.
- Two runs per codec; ranges are shown. The device was later disconnected, so
  no more repeats were added.
- Time to the **first sound** is shorter and is not what this table measures;
  the table is for having all 4 s of PCM ready.

Raw data: [benchmarks/decode_4s_2t1c_sm_s931b.json](benchmarks/decode_4s_2t1c_sm_s931b.json).
