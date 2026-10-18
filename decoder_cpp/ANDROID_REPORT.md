# SpectroStream Android Decoder — Полный отчёт

Дата: 2026-07-12
Устройство: Samsung Galaxy S24 (SM-S931B), Exynos 2400, Android 15, 12 GB RAM

---

## Статус: READY FOR FLUTTER INTEGRATION

f25 FP32 декодирует 162-секундный трек быстрее realtime (RTF 0.79, 6 threads).
f75 FP32 context-aware decode — sample-exact, SNR 99.8 dB vs Linux, без boundary artifacts.
C ABI — все тесты пройдены. Библиотека готова к подключению через Flutter FFI.

---

## 1. Артефакты сборки

### Библиотека для Flutter

```
decoder_cpp/build-android-arm64/libspectrostream_decoder.so   — 5.2 MiB (stripped)
```

Рядом нужен STL runtime:

```
libc++_shared.so   — 8.9 MiB
```

Источник: `$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so`

### Параметры сборки

| Параметр | Значение |
|----------|----------|
| ABI | arm64-v8a |
| minSdk | 26 |
| STL | c++_shared |
| NDK | r28c (28.2.13676358) |
| TFLite | 2.18.0 (builtin ops only) |
| Delegate | XNNPACK CPU |
| Build type | Release |
| Page alignment | 16 KiB (Android 15 compatible) |

### Dynamic dependencies (только system libs)

```
libm.so
libdl.so
liblog.so
libc++_shared.so
libc.so
```

Нет зависимости от Python, TensorFlow full, ONNX, Flex delegate.

### Отладочные executable (не нужны Flutter, для adb shell)

```
decoder_cpp/build-android-arm64/spectrostream_decode   — 3.8 MiB
decoder_cpp/build-android-arm64/test_c_api             — 3.8 MiB
```

---

## 2. C ABI

### Header

```
decoder_cpp/include/spectrostream/decoder_c_api.h
```

### Exported symbols (подтверждено llvm-nm)

```
T spectrostream_decoder_create
T spectrostream_decoder_decode_file
T spectrostream_decoder_free_pcm
T spectrostream_decoder_destroy
T spectrostream_decoder_last_error
```

### Сигнатуры

```c
// Создать decoder. При ошибке handle != NULL, но decoder внутри = NULL.
SpectroStreamDecoderHandle spectrostream_decoder_create(
    const char* model_path,        // абсолютный путь к .tflite
    const char* codebooks_path,    // абсолютный путь к rvq_codebooks.f32
    const char* window_path,       // абсолютный путь к istft_window_f960.f32
    int num_threads                // рекомендация: 4–6
);

// Декодировать .sst → PCM float32 interleaved stereo.
// Возвращает 0 = ok, -1 = ошибка.
int spectrostream_decoder_decode_file(
    SpectroStreamDecoderHandle handle,
    const char* sst_path,
    float** pcm_out,               // [out] malloc'd buffer, освобождать через free_pcm
    int64_t* frame_count_out,      // [out] PCM frames (samples per channel)
    int* sample_rate_out,          // [out] всегда 48000
    int* channels_out              // [out] всегда 2
);

void spectrostream_decoder_free_pcm(float* pcm);
void spectrostream_decoder_destroy(SpectroStreamDecoderHandle handle);
const char* spectrostream_decoder_last_error(SpectroStreamDecoderHandle handle);
```

### Гарантии

- `SpectroStreamDecoderHandle` = `void*`
- Нет C++ exceptions через границу
- Нет STL типов в public API
- Thread safety: один handle — один поток; разные handles — безопасно параллельно
- Повторный decode одним handle — работает (подтверждено тестом)
- `spectrostream_decoder_destroy(NULL)` — безопасно
- Проверка ошибки создания: `spectrostream_decoder_last_error(h)` — пустая строка = ok

### Результат теста на устройстве

```
TEST: null handle safety... OK
TEST: error handling... OK
TEST: create/destroy... OK
TEST: decode file... OK (frames=7779614, sr=48000, ch=2)
TEST: double decode (reuse handle)... OK (both decodes: 7779614 frames)

ALL TESTS PASSED
```

---

## 3. Модели и assets

### Файлы для устройства

| Файл | Размер | Назначение |
|------|--------|------------|
| `spectrostream_decoder_core_fp32_f75.tflite` | 136 MiB | Context-aware, лучшее качество |
| `spectrostream_decoder_core_fp32_f25.tflite` | 136 MiB | Быстрый, RTF < 1 на 6 threads |
| `spectrostream_decoder_core_fp16_f25.tflite` | 68 MiB | FP16 быстрый (ещё быстрее) |
| `rvq_codebooks.f32` | 64 MiB | RVQ codebooks (64×1024×256 float32) |
| `istft_window_f960.f32` | 3.8 KiB | iSTFT window (960 float32) |

### Размещение

**НЕ класть в APK assets** — суммарно 200+ MiB.

Рекомендация: скачивать при первом запуске в app-specific storage.

```
/data/data/com.example.app/files/spectrostream/
├── spectrostream_decoder_core_fp32_f25.tflite
├── rvq_codebooks.f32
└── istft_window_f960.f32
```

Пути передаются как абсолютные строки в `spectrostream_decoder_create()`.

---

## 4. Результаты decode на устройстве

### Correctness — f75 FP32 context-aware

```
Sample rate:    48000 Hz
Channels:       2 (stereo)
PCM frames:     7,779,614   ← EXACT MATCH vs Linux
Audio duration: 162.075 s
```

### Сравнение Android ARM64 vs Linux x86-64

| Метрика | Значение |
|---------|----------|
| Sample count | **EXACT MATCH** (15,559,228 interleaved samples) |
| SNR | **99.8 dB** |
| Max abs error | 0.000031 |
| RMSE | 0.0000026 |
| NaN/Inf | 0 |
| Boundary clicks | **Нет** |

Причина остаточной разницы: XNNPACK ARM NEON vs x86 SSE float rounding. Не слышима.

### Выходной WAV (доступен для прослушивания)

```
media/reconstructed/android/reconstructed_android_f75.wav
```

PCM16 stereo 48kHz, 30 MiB, 162 секунды. Без артефактов.

---

## 5. Производительность

### Thread scaling — Samsung Galaxy S24

| Model | Threads | Inference | Total | RTF | Realtime? |
|-------|--------:|----------:|------:|----:|-----------|
| f25 FP32 | 2 | 319,114 ms | 319,635 ms | 1.97 | Нет |
| f25 FP32 | 4 | 192,260 ms | 192,826 ms | 1.19 | Нет |
| **f25 FP32** | **6** | **127,041 ms** | **127,511 ms** | **0.79** | **Да** |
| f75 FP32 | 4 | 680,778 ms | 682,196 ms | 4.21 | Нет |
| f75 FP32 | 6 | 418,584 ms | 419,873 ms | 2.59 | Нет |

### Выводы

- **f25 FP32 с 6 threads: RTF 0.79** — декодирует быстрее realtime
- f75 FP32: 2.6–4.2x медленнее realtime (зависит от потоков)
- Model load: 143–390 ms
- Узкое место: LiteRT inference (>99.8% общего времени)
- SST parse + RVQ + iSTFT = менее 1.5 секунды на 162 секунды аудио

### Thread scaling efficiency

```
2 → 4 threads: ×1.66 speedup
4 → 6 threads: ×1.51 speedup
```

Diminishing returns после 4 threads (малые ядра Exynos менее эффективны).

---

## 6. Интеграция в Flutter

### Вариант 1: Pre-built .so (рекомендуется)

```
flutter_app/android/app/src/main/jniLibs/arm64-v8a/
├── libspectrostream_decoder.so    ← из build-android-arm64/
└── libc++_shared.so               ← из NDK sysroot
```

Flutter автоматически пакует jniLibs в APK.

### Вариант 2: CMake через Gradle

```groovy
android {
    defaultConfig {
        ndk { abiFilters 'arm64-v8a' }
        externalNativeBuild {
            cmake {
                arguments '-DBUILD_SHARED_LIB=ON',
                          '-DBUILD_CLI=OFF',
                          '-DBUILD_TESTS=OFF',
                          '-DENABLE_SANITIZERS=OFF',
                          '-DTFLITE_HOST_TOOLS_DIR=/path/to/decoder_cpp/build',
                          '-DKLEIDIAI_SOURCE_DIR=/path/to/decoder_cpp/third_party/kleidiai'
            }
        }
    }
    externalNativeBuild {
        cmake {
            path '/path/to/decoder_cpp/CMakeLists.txt'
            version '3.22.0+'
        }
    }
}
```

### Dart FFI binding (пример)

```dart
import 'dart:ffi';
import 'package:ffi/ffi.dart';

typedef NativeCreate = Pointer<Void> Function(
    Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, Int32);
typedef NativeDecodeFile = Int32 Function(
    Pointer<Void>, Pointer<Utf8>, Pointer<Pointer<Float>>,
    Pointer<Int64>, Pointer<Int32>, Pointer<Int32>);
typedef NativeFreePcm = Void Function(Pointer<Float>);
typedef NativeDestroy = Void Function(Pointer<Void>);
typedef NativeLastError = Pointer<Utf8> Function(Pointer<Void>);

class SpectroStreamDecoder {
  late final DynamicLibrary _lib;
  late final Pointer<Void> _handle;

  SpectroStreamDecoder({
    required String modelPath,
    required String codebooksPath,
    required String windowPath,
    int threads = 6,
  }) {
    _lib = DynamicLibrary.open('libspectrostream_decoder.so');
    final create = _lib.lookupFunction<NativeCreate,
        Pointer<Void> Function(Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, int)>(
        'spectrostream_decoder_create');

    final m = modelPath.toNativeUtf8();
    final c = codebooksPath.toNativeUtf8();
    final w = windowPath.toNativeUtf8();
    _handle = create(m, c, w, threads);
    malloc.free(m); malloc.free(c); malloc.free(w);

    final err = lastError;
    if (err.isNotEmpty) throw Exception('SpectroStream init: $err');
  }

  String get lastError {
    final fn = _lib.lookupFunction<NativeLastError,
        Pointer<Utf8> Function(Pointer<Void>)>(
        'spectrostream_decoder_last_error');
    return fn(_handle).toDartString();
  }

  void dispose() {
    final fn = _lib.lookupFunction<NativeDestroy,
        void Function(Pointer<Void>)>('spectrostream_decoder_destroy');
    fn(_handle);
  }
}
```

### Критичные правила для Flutter-агента

1. `decode_file` — **блокирующий**, декодирует весь трек целиком. Не вызывать на UI isolate.
2. `free_pcm` — **обязателен** после каждого decode, иначе утечка памяти.
3. Один handle — один поток. Для параллельного decode создавать отдельные handles.
4. Формат выхода: float32 interleaved (L R L R ...), нужна конвертация в PCM16 для AudioTrack.
5. Model load ~150–400 ms — делать при инициализации, не при каждом decode.

---

## 7. Выбор модели

| Сценарий | Модель | Threads | RTF (S24) | Качество |
|----------|--------|--------:|----------:|----------|
| Offline decode | f25 FP32 | 6 | 0.79 | Хорошее (есть clicks на boundary) |
| High-quality offline | f75 FP32 | 6 | 2.59 | Отличное (без артефактов) |
| Realtime preview | f25 FP16 | 6 | ~0.4* | Хорошее |
| Best quality + speed | f75 FP16 | 6 | ~1.3* | Отличное |

\* FP16 оценка, реальные замеры после экспорта модели.

**Рекомендация для первого Flutter-прототипа:** f25 FP32, 6 threads. Уже быстрее realtime.

---

## 8. Известные ограничения

1. **f75 FP32 не realtime** — RTF 2.59 на S24. Для фонового decode подходит, для playback нет.
2. **FP16 f75 не экспортирована** — нужен Python из `encoder_service/`.
3. **GPU delegate не тестирован** — собирается с `--gpu`, может дать RTF < 1.0 для f75.
4. **Streaming decode отсутствует** — текущий API обрабатывает весь файл.
5. **~200 MiB RAM baseline** — модель 136 MiB + codebooks 64 MiB + activations.
6. **Только arm64-v8a** — armeabi-v7a не нужен (minSdk 26).

---

## 9. Структура проекта

```
decoder_cpp/
├── CMakeLists.txt                        ← поддерживает Android cross-compile
├── android/
│   ├── build.sh                          ← полная автоматическая сборка
│   ├── deploy.sh                         ← push на устройство
│   ├── benchmark.sh                      ← thread scaling benchmark
│   ├── thermal_test.sh                   ← sustained load test
│   ├── memory_profile.sh                 ← RSS tracking
│   ├── gpu_probe.sh                      ← GPU delegate test
│   ├── verify.sh                         ← сравнение с Linux reference
│   ├── run_all.sh                        ← полный pipeline
│   └── results/
│       └── ANDROID_DEVICE_REPORT.md      ← отчёт по устройству
├── build-android-arm64/
│   ├── libspectrostream_decoder.so       ← ЭТО кладётся в jniLibs
│   ├── spectrostream_decode              ← CLI для отладки
│   └── test_c_api                        ← smoke test
├── include/spectrostream/
│   └── decoder_c_api.h                   ← контракт FFI
├── models/                               ← скачивать отдельно, не в APK
├── third_party/
│   ├── tensorflow/                       ← TFLite source
│   └── kleidiai/                         ← XNNPACK ARM dep
└── src/                                  ← portable core (не трогать)
```

---

## 10. Команды воспроизведения

```bash
cd <repository>/decoder_cpp

# Сборка (если ещё не собрано)
./android/build.sh

# Deploy на подключённое устройство
./android/deploy.sh

# Decode на устройстве
adb shell "cd /data/local/tmp/spectrostream && \
  LD_LIBRARY_PATH=. ./spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f25.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input data/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output output/decoded.wav --threads 6"

# Забрать результат
adb pull /data/local/tmp/spectrostream/output/decoded.wav .
```
