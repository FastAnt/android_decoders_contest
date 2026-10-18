# Android Build Report — SpectroStream C++ Decoder

Отчёт для интеграции в Flutter-приложение.

---

## Артефакты сборки

### Основная библиотека

```
build-android-arm64/libspectrostream_decoder.so
```

- ABI: `arm64-v8a`
- minSdk: 26
- STL: `c++_shared` (требует `libc++_shared.so` рядом)
- Размер stripped: **5.2 MiB**
- Зависимости: нет внешних `.so` кроме `libc++_shared.so`

### Runtime зависимость

```
$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so
```

Эта библиотека должна лежать рядом с `libspectrostream_decoder.so` в `jniLibs/arm64-v8a/`.

### Тестовый CLI (не нужен Flutter, только для отладки)

```
build-android-arm64/spectrostream_decode     — 3.8 MiB stripped
build-android-arm64/test_c_api               — 3.8 MiB stripped
```

---

## C ABI для Flutter FFI

### Header

```
include/spectrostream/decoder_c_api.h
```

### Функции

```c
// Создать decoder. Возвращает opaque handle.
// При ошибке возвращает handle с decoder=NULL, ошибка в last_error.
SpectroStreamDecoderHandle spectrostream_decoder_create(
    const char* model_path,        // путь к .tflite
    const char* codebooks_path,    // путь к rvq_codebooks.f32
    const char* window_path,       // путь к istft_window_f960.f32
    int num_threads                // рекомендация: 4 для arm64
);

// Декодировать .sst файл в PCM float32 interleaved stereo.
// pcm_out — выделяется библиотекой, освобождать через free_pcm.
// Возвращает 0 при успехе, -1 при ошибке.
int spectrostream_decoder_decode_file(
    SpectroStreamDecoderHandle handle,
    const char* sst_path,
    float** pcm_out,               // [out] interleaved float32
    int64_t* frame_count_out,      // [out] PCM frames (samples per channel)
    int* sample_rate_out,          // [out] всегда 48000
    int* channels_out              // [out] всегда 2
);

// Освободить PCM буфер.
void spectrostream_decoder_free_pcm(float* pcm);

// Уничтожить decoder.
void spectrostream_decoder_destroy(SpectroStreamDecoderHandle handle);

// Получить текст последней ошибки (не нужно освобождать).
const char* spectrostream_decoder_last_error(SpectroStreamDecoderHandle handle);
```

### Гарантии ABI

- Нет C++ exceptions через границу (всё ловится внутри)
- Нет STL типов в public API (только `const char*`, `float*`, `int`, `int64_t`)
- `SpectroStreamDecoderHandle` — это `void*`
- Thread safety: один handle = один поток. Разные handles можно из разных потоков.
- Повторный decode одним handle — работает (проверено тестом)
- `spectrostream_decoder_destroy(NULL)` — безопасно

### Коды ошибок

- `spectrostream_decoder_create` возвращает non-null handle даже при ошибке
- Проверять: `spectrostream_decoder_last_error(handle)` — если строка не пустая, decoder не инициализирован
- `spectrostream_decoder_decode_file` возвращает `-1` при ошибке, `0` при успехе

---

## Dart FFI Binding (пример)

```dart
import 'dart:ffi';
import 'dart:io';
import 'package:ffi/ffi.dart';

typedef SpectroStreamHandle = Pointer<Void>;

// Native function signatures
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
    int threads = 4,
  }) {
    _lib = DynamicLibrary.open('libspectrostream_decoder.so');

    final create = _lib.lookupFunction<NativeCreate,
        Pointer<Void> Function(Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, int)>(
        'spectrostream_decoder_create');

    final m = modelPath.toNativeUtf8();
    final c = codebooksPath.toNativeUtf8();
    final w = windowPath.toNativeUtf8();
    _handle = create(m, c, w, threads);
    malloc.free(m);
    malloc.free(c);
    malloc.free(w);

    final err = lastError();
    if (err.isNotEmpty) {
      throw Exception('SpectroStream init failed: $err');
    }
  }

  String lastError() {
    final fn = _lib.lookupFunction<NativeLastError,
        Pointer<Utf8> Function(Pointer<Void>)>(
        'spectrostream_decoder_last_error');
    return fn(_handle).toDartString();
  }

  void dispose() {
    final destroy = _lib.lookupFunction<NativeDestroy,
        void Function(Pointer<Void>)>('spectrostream_decoder_destroy');
    destroy(_handle);
  }
}
```

---

## Модели и assets для Flutter

### Файлы, которые нужны на устройстве

| Файл | Размер | Описание |
|------|--------|----------|
| `spectrostream_decoder_core_fp32_f75.tflite` | 136 MiB | Основная модель (context-aware, качественная) |
| `spectrostream_decoder_core_fp32_f25.tflite` | 136 MiB | Быстрая модель (без контекста, есть boundary artifacts) |
| `spectrostream_decoder_core_fp16_f25.tflite` | 68 MiB | Быстрая модель FP16 (в 2 раза меньше) |
| `rvq_codebooks.f32` | 64 MiB | Codebooks для RVQ dequantization |
| `istft_window_f960.f32` | 3.8 KiB | iSTFT window function |

### Стратегия размещения в Flutter

**НЕ класть в APK assets** — суммарно 200+ MiB сырых данных.

Рекомендуемый подход:

1. Хранить модели на внешнем хранилище или app-specific storage
2. Скачивать при первом запуске (или bundlить в expansion file)
3. Пути передавать в `spectrostream_decoder_create` как абсолютные строки

Пример расположения на устройстве:

```
/data/data/com.example.app/files/spectrostream/
├── spectrostream_decoder_core_fp32_f75.tflite
├── rvq_codebooks.f32
└── istft_window_f960.f32
```

---

## Сборка .so для Flutter-проекта

### Вариант 1: Pre-built .so (рекомендуется для начала)

```
android/app/src/main/jniLibs/arm64-v8a/
├── libspectrostream_decoder.so
└── libc++_shared.so
```

Flutter автоматически пакует содержимое `jniLibs/` в APK.

### Вариант 2: CMake интеграция через Gradle

В `android/app/build.gradle`:

```groovy
android {
    defaultConfig {
        ndk {
            abiFilters 'arm64-v8a'
        }
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

**Внимание**: первая сборка через Gradle займёт 5+ минут (компиляция TFLite).

### Вариант 3: Pre-build скриптом

```bash
cd /path/to/decoder_cpp
./android/build.sh
cp build-android-arm64/libspectrostream_decoder.so \
   /path/to/flutter_app/android/app/src/main/jniLibs/arm64-v8a/
```

---

## Команды для воспроизводимой сборки

```bash
cd decoder_cpp

# 1. Убедиться что Linux build есть (нужен host flatc)
test -f build/flatbuffers-flatc/bin/flatc || {
    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release
    cmake --build . -j$(nproc)
    cd ..
}

# 2. Собрать Android arm64
./android/build.sh

# 3. Результат
ls -lh build-android-arm64/libspectrostream_decoder.so
```

NDK автоматически определяется из `$HOME/Android/Sdk/ndk/` (берётся последняя версия).

Явно:

```bash
export ANDROID_NDK_HOME=$HOME/Android/Sdk/ndk/28.2.13676358
./android/build.sh
```

---

## Производительность (Linux baseline, для ориентира)

| Конфигурация | RTF | Время decode 162s аудио |
|--------------|-----|------------------------|
| FP32 f75, 8 threads, x86-64 | 2.46 | 399 s |
| FP32 f25, 8 threads, x86-64 | 0.88 | 143 s |

На Android ARM64 с XNNPACK + NEON ожидается:
- f25 FP32: RTF ~0.5–1.5 (зависит от SoC)
- f75 FP32: RTF ~1.5–4.0
- f25 FP16: RTF ~0.3–0.8

**Реальные цифры будут после запуска `./android/benchmark.sh` на устройстве.**

---

## Выход decode

- Sample rate: 48000 Hz
- Channels: 2 (stereo)
- Format: float32 interleaved (L R L R ...)
- Длина: точно `original_samples` из SST header
- Для воспроизведения: конвертировать в PCM16 или передать в AudioTrack как float

---

## Выбор модели для Flutter

| Модель | Качество | Скорость | RAM | Рекомендация |
|--------|----------|----------|-----|--------------|
| f75 FP32 | Лучшее (56 dB SNR, без артефактов) | Медленная | ~400 MiB | Оффлайн high-quality |
| f25 FP32 | Хорошее (есть boundary clicks) | Быстрая | ~250 MiB | Быстрый preview |
| f25 FP16 | Хорошее | Самая быстрая | ~180 MiB | Real-time на среднем SoC |
| f75 FP16 | Лучшее | Средняя | ~300 MiB | **Ещё не экспортирована** |

Для первого Flutter прототипа: начать с **f25 FP32**, потом перейти на f75 FP16 когда модель будет готова.

---

## Что НЕ входит в библиотеку

- Сетевая загрузка SST файлов (streaming)
- AudioTrack/Oboe playback
- UI
- Управление скачиванием моделей
- Background service

Библиотека — чистый decode: `.sst` path in → PCM float32 out.

---

## Структура файлов для Flutter-агента

```
decoder_cpp/
├── android/
│   ├── build.sh              ← собрать .so
│   ├── deploy.sh             ← push на девайс для тестов
│   ├── benchmark.sh          ← замеры
│   └── ...
├── build-android-arm64/
│   ├── libspectrostream_decoder.so   ← ЭТО кладётся в jniLibs
│   └── spectrostream_decode          ← CLI для отладки на девайсе
├── include/
│   └── spectrostream/
│       └── decoder_c_api.h           ← контракт для FFI binding
├── models/                           ← НЕ в APK, скачивать отдельно
│   ├── spectrostream_decoder_core_fp32_f75.tflite
│   ├── rvq_codebooks.f32
│   └── istft_window_f960.f32
└── CMakeLists.txt
```

---

## Известные ограничения

1. **FP16 f75 модель не экспортирована** — нужен Python скрипт из `encoder_service/`
2. **GPU delegate** — собирается с `--gpu`, но не тестирован на реальном устройстве
3. **Потоковый decode** — текущий API обрабатывает весь файл целиком. Для streaming playback нужен новый API с блочной обработкой.
4. **Только arm64-v8a** — armeabi-v7a не тестировался и не нужен (minSdk 26 = почти все arm64)
