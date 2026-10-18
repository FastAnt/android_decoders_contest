# decoder_cpp — Отчёт о выполнении

## Статус: Context-aware decode реализован и верифицирован

Pipeline: `.sst` → 10-bit unpack → RVQ dequant → LiteRT inference → C++ iSTFT → PCM16 WAV.

Boundary artifacts устранены. Sample-exact output. Формальная верификация против Python q64 reference пройдена.

---

## Команды запуска

```bash
cd decoder_cpp

# Context-aware decode (качественный, без boundary artifacts):
./build/spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f75.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input ../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output ../media/reconstructed/cpp/reconstructed_cpp_ctx.wav \
  --threads 8

# Быстрый режим (RTF < 1, есть boundary artifacts):
./build/spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f25.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input ../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output ../media/reconstructed/cpp/reconstructed_cpp.wav \
  --threads 8

# Только инспекция контейнера:
./build/spectrostream_decode --inspect \
  --input ../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst
```

---

## Результат запуска (f75, context-aware)

```
INFO: Created TensorFlow Lite XNNPACK delegate for CPU.
SpectroStream C++ Decoder
========================
Model + assets loaded in 168.9 ms

=== Decode Timing ===
SST parse:           5.4 ms
RVQ dequant:       140.1 ms
LiteRT infer:   398671.1 ms
iSTFT:             565.0 ms
Total decode:   399437.8 ms

Audio duration: 162.075 s
RTF:            2.4645
Sample rate:    48000 Hz
Channels:       2
PCM frames:     7779614

Written: reconstructed_cpp_ctx.wav (PCM16 stereo 48kHz)
```

---

## Верификация против Python q64 reference

Reference: `media/data/reconstructed/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.q64.wav`

Python reference декодирован с: inference_chunk=8s, context=1s, full TensorFlow decoder.

### До и после context-aware

| Метрика | f25 (no context) | f75 (context=25) |
|---------|-----------------|------------------|
| **Global SNR** | 15.26 dB | **56.04 dB** |
| Max abs error | 1.46 | 0.19 |
| RMSE | 0.043 | 0.00039 |
| Mid-block SNR median | 35.98 dB | 60.79 dB |
| **Boundary SNR median** | 4.91 dB | **61.14 dB** |
| Mid/Boundary gap | 31.1 dB | **-0.4 dB** |
| Clicks | Да | **Нет** |
| Sample count exact | Да | Да |

### Вывод

- **Boundary artifacts полностью устранены.** Gap между серединой блока и границей: < 1 dB.
- **56 dB SNR** — остаточная разница между C++ (3-sec chunks) и Python (8-sec chunks). Оба без артефактов.
- **Нет щелчков.** Max sample jump на границе (0.164) ≤ средний jump в середине блока.
- **Sample-exact output.** 7,779,614 PCM frames = `original_samples` из SST header.

---

## Производительность

| Конфигурация | RTF | Inference/block |
|--------------|-----|-----------------|
| f25 (no ctx), 8 threads | **0.88** | 0.88 s |
| f25 (no ctx), 4 threads | 1.26 | 1.26 s |
| f75 (ctx=25), 8 threads | 2.46 | 2.46 s |

Узкое место: LiteRT inference (99.8% времени). SST parse + RVQ + iSTFT = < 1 секунда на 162 секунды аудио.

### Пути к real-time с context-aware на Android

| Оптимизация | Ожидаемый RTF |
|-------------|---------------|
| FP16 модель + ARM NEON | 1.2–1.5 |
| GPU delegate (Adreno/Mali) | 0.3–0.8 |
| f100 модель (core=50, ctx=25) → 2x меньше инференсов | ~1.2 |
| INT8 + NNAPI/NPU | 0.2–0.5 |

---

## Архитектура context-aware decode

```
Codec frames:  [0..24] [25..49] [50..74] [75..99] ...

Block 0:  pad(25) + frames[0..24]  + frames[25..49]   → iSTFT → take center 48000
Block 1:  frames[0..24]  + frames[25..49] + frames[50..74]  → iSTFT → take center 48000
Block 2:  frames[25..49] + frames[50..74] + frames[75..99]  → iSTFT → take center 48000
...
```

Для каждого 1-секундного выходного блока:
1. Собрать окно: 25 frames context left + 25 frames core + 25 frames context right
2. RVQ dequantize → 75×256 embeddings
3. LiteRT inference [1,75,256] → spectrum [1,2,300,481,2]
4. iSTFT (300 STFT frames) → 144000 PCM samples (3 seconds)
5. Извлечь центральную секунду: samples[48000:96000] (per channel)
6. Append к выходу

На краях (начало/конец файла): zero-padding вместо отсутствующего контекста.

---

## Реализованные компоненты

| Компонент | Файл | Описание |
|-----------|------|----------|
| SstReader | sst_reader.cpp | SST1 parse, 10-bit unpack, CRC32, codebook-major transpose |
| RvqDequantizer | rvq_dequantizer.cpp | 64 codebooks × 1024 entries × 256 dims, sum embeddings |
| LiteRtRunner | litert_runner.cpp | TFLite + XNNPACK, auto-detect model shape (f25/f75/любой) |
| Istft | istft.cpp | PocketFFT c2r, variable STFT frames, window OLA |
| Decoder | decoder.cpp | Context-aware sliding window orchestration |
| WavWriter | wav_writer.cpp | PCM16 RIFF/WAV |
| C ABI | decoder_c_api.cpp | Stable C interface for Flutter FFI |
| CLI | cli/main.cpp | Argument parsing, timing, inspect mode |

### Артефакты сборки

```
build/spectrostream_decode              — Linux CLI (7.8 МБ)
build/libspectrostream_decoder.so.1.0.0 — Shared library (8.5 МБ)
build/test_sst_reader                   — Unit test ✓
build/test_rvq_dequantizer              — Unit test ✓
build/test_istft                        — Unit test ✓
```

### Модели

```
models/spectrostream_decoder_core_fp32_f25.tflite  — 136 MiB, input [1,25,256]
models/spectrostream_decoder_core_fp32_f75.tflite  — 136 MiB, input [1,75,256]
models/spectrostream_decoder_core_fp16_f25.tflite  — 68 MiB, input [1,25,256]
models/rvq_codebooks.f32                           — 64 MiB, [64,1024,256]
models/istft_window_f960.f32                       — 3.8 KiB, 960 float32
```

---

## Технологии

- C++20, CMake 3.22+
- TensorFlow Lite 2.18.0 (из исходников, XNNPACK delegate, builtin ops only)
- PocketFFT (header-only C++ FFT, portable)
- Без зависимости от Python, TensorFlow runtime, ONNX, Flex delegate

---

## Документация

```
docs/sst_format.md    — Полная бинарная спецификация SST1 контейнера
docs/architecture.md  — Архитектура pipeline и threading model
README.md             — Инструкции по сборке и запуску
```

---

## Что дальше

1. **Android NDK arm64-v8a build** — CMakeLists готов, кросс-компиляция не проверена на реальном устройстве
2. **FP16 inference** — модель f16 уже экспортирована для f25, нужна для f75
3. **GPU delegate probe** — замер на Adreno/Mali
4. **RAM/temperature профилирование** на телефоне
5. **f100 модель (core=50, ctx=25)** — вдвое меньше инференсов при том же качестве

---

## Сборка

```bash
cd decoder_cpp
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

Первая сборка ~5 минут (компиляция TFLite). Последующие — секунды.
