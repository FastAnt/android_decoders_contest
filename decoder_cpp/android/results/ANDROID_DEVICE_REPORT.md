# Android Device Report — SpectroStream Decoder

## Устройство

| Параметр | Значение |
|----------|----------|
| Manufacturer | Samsung |
| Model | SM-S931B (Galaxy S24) |
| SoC | Exynos 2400 |
| Android | 15 |
| API level | 35 |
| ABI | arm64-v8a |
| RAM | 12 GB |
| CPU cores | 8 (1×3.2 GHz + 3×2.9 GHz + 4×1.95 GHz) |

---

## Проверка артефактов

### Архитектура

```
libspectrostream_decoder.so: ELF 64-bit LSB shared object, ARM aarch64
spectrostream_decode:        ELF 64-bit LSB pie executable, ARM aarch64
test_c_api:                  ELF 64-bit LSB pie executable, ARM aarch64
```

### Dynamic dependencies

```
libm.so
libdl.so
liblog.so
libc++_shared.so
libc.so
```

Нет зависимостей от Python, TensorFlow full, ONNX, Flex.

### Exported C ABI symbols

```
T spectrostream_decoder_create
T spectrostream_decoder_decode_file
T spectrostream_decoder_free_pcm
T spectrostream_decoder_destroy
T spectrostream_decoder_last_error
```

Все 5 обязательных символов — экспортированы.

### 16 KiB page alignment (Android 15)

```
LOAD segments align = 0x4000 (16384 bytes)
```

Совместимо с Android 15 16 KiB pages.

### Размеры (stripped)

| Файл | Размер |
|------|--------|
| libspectrostream_decoder.so | 5.2 MiB |
| spectrostream_decode | 3.8 MiB |
| test_c_api | 3.8 MiB |
| libc++_shared.so | 8.9 MiB |

### Checksums — Host vs Device

Все SHA-256 совпали. Целостность данных на устройстве подтверждена.

---

## C ABI Smoke Test

**Результат: ALL TESTS PASSED**

```
TEST: null handle safety... OK
TEST: error handling... OK (got error: Cannot open codebook file: /nonexistent/codebooks.f32...)
TEST: create/destroy... OK
TEST: decode file... OK (frames=7779614, sr=48000, ch=2)
TEST: double decode (reuse handle)... OK (both decodes: 7779614 frames)
```

Подтверждено:
- handle создаётся
- decode возвращает 7,779,614 PCM frames
- sample rate = 48000, channels = 2
- повторный decode тем же handle — работает
- error handling без crash
- NULL handle — безопасно

---

## Полный decode — f75 FP32 context-aware

```
Model + assets loaded in 143.3 ms
Backend: XNNPACK CPU

=== Decode Timing ===
SST parse:           3.5 ms
RVQ dequant:       256.8 ms
LiteRT infer:   680778.2 ms
iSTFT:            1072.6 ms
Total decode:   682195.5 ms

Audio duration: 162.075 s
RTF:            4.2091
Sample rate:    48000 Hz
Channels:       2
PCM frames:     7779614
```

**RTF 4.21** (4 threads) — в 4.2 раза медленнее realtime.

---

## Сравнение Android output vs Linux reference

```
Android: 15,559,228 samples, 48000 Hz, 2 ch, 7,779,614 frames
Linux:   15,559,228 samples, 48000 Hz, 2 ch, 7,779,614 frames

Sample count: EXACT MATCH
Max abs error:  0.000031
RMSE:           0.00000255
SNR:            99.8 dB

No NaN/Inf: OK
Ch0 boundary check: OK
Ch1 boundary check: OK

VERDICT: EXCELLENT - Android output matches Linux (SNR > 80 dB)
```

**99.8 dB SNR** — практически bit-exact. Разница вызвана только различиями XNNPACK ARM vs x86 float rounding.

Нет boundary clicks. Нет NaN/Inf. Sample count exact.

---

## CPU Benchmark — Thread Scaling

| Model | Threads | LiteRT Infer | Total Decode | RTF |
|-------|--------:|-------------:|-------------:|----:|
| f25 FP32 | 2 | 319,114 ms | 319,635 ms | **1.97** |
| f25 FP32 | 4 | 192,260 ms | 192,826 ms | **1.19** |
| f25 FP32 | 6 | 127,041 ms | 127,511 ms | **0.79** |
| f75 FP32 | 4 | 680,778 ms | 682,196 ms | **4.21** |
| f75 FP32 | 6 | 418,584 ms | 419,873 ms | **2.59** |

### Ключевые выводы

1. **f25 FP32 с 6 threads: RTF 0.79 — быстрее realtime** на Galaxy S24
2. f75 FP32 с 6 threads: RTF 2.59 — в 2.5 раза медленнее realtime
3. Thread scaling эффективен: 2→4 = ~1.65x, 4→6 = ~1.5x
4. Узкое место: 99.8% времени — LiteRT inference

### Model load time

~143–390 ms (зависит от того, горячий ли файловый кэш).

---

## Декодированный WAV

```
android/results/reconstructed_android_f75.wav
```

- PCM16 stereo 48kHz
- 30 MiB
- 162.075 секунд
- 7,779,614 PCM frames
- Без boundary artifacts
- Готов к прослушиванию

---

## Итоговый статус

### Что работает

| Критерий | Статус |
|----------|--------|
| arm64-v8a build | ✅ |
| Binary запускается на устройстве | ✅ |
| C ABI symbols экспортированы | ✅ |
| 16 KiB alignment | ✅ |
| Decode f75 context-aware | ✅ |
| Sample count exact | ✅ |
| SNR > 80 dB vs Linux | ✅ (99.8 dB) |
| Нет boundary clicks | ✅ |
| Нет NaN/Inf | ✅ |
| C ABI smoke test | ✅ |
| f25 realtime на 6 threads | ✅ (RTF 0.79) |

### Что не проверялось в этом запуске

- f25 1 thread (ожидается RTF ~3.8)
- f75 1/2 threads
- FP16 модель
- GPU delegate
- Peak RSS
- Thermal stability (5 min)
- NNAPI

---

## Рекомендации для следующего шага

### Для Flutter (offline decode)

Использовать **f25 FP32 с 6 threads** — уже работает быстрее realtime.

### Для real-time playback

1. Экспортировать **FP16 f25** → ожидаемый RTF ~0.4–0.5
2. Или экспортировать **f75 FP16** → RTF ~1.3–1.7 с 6 threads (но без clicks)

### Для минимальной памяти

f25 FP32 (без context) — модель 136 MiB + codebooks 64 MiB ≈ 200 MiB baseline.

### GPU delegate

Потенциально может дать RTF < 1.0 для f75, но требует отдельного теста (`./android/build.sh --gpu`).

---

## Воспроизведение результата

```bash
cd <repository>/decoder_cpp

# Build (если не собрано)
./android/build.sh

# Deploy
./android/deploy.sh

# Decode
adb shell "cd /data/local/tmp/spectrostream && \
  LD_LIBRARY_PATH=. ./spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f75.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input data/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output output/decoded.wav \
  --threads 6"

# Pull result
adb pull /data/local/tmp/spectrostream/output/decoded.wav .
```
