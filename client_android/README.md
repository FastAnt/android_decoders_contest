# Neural Codecs Android Client

Flutter-приложение для сравнения времени запуска MP3, SpectroStream и SAGE.
SpectroStream декодируется через `dart:ffi` и C++ runtime, SAGE — через
Kotlin-мост к LiteRT; в приложении доступны сетевые профили, выбор модели
SpectroStream и числа потоков CPU.

## Подготовка

Нужны Flutter с Dart SDK, совместимым с `pubspec.yaml` (`^3.10.7`), Android SDK,
NDK и устройство или эмулятор `arm64-v8a` с Android API 26+.
Проверка widget-теста выполнена на Flutter 3.44.8 / Dart 3.12.2;
исходный lockfile создан другим SDK. `flutter pub get` на новом SDK может
обновить зависимости, закреплённые самим Flutter; такие изменения проверяйте
и фиксируйте отдельно от изменения документации.

Исходники Flutter/Android и Gradle Wrapper хранятся в Git. Модели и нативные
`.so` нужно подготовить перед сборкой:

- `assets/audio/demo.mp3`, `assets/spectrostream/demo.sst` и
  `assets/sage/demo.sage` — небольшой сгенерированный демотрек, уже включён
  в репозиторий. Все три режима используют один и тот же трек.
- `assets/spectrostream/` — `spectrostream_decoder_core_fp32_f25.tflite`,
  `spectrostream_decoder_core_fp32_f75.tflite`,
  `spectrostream_decoder_core_fp16_f25.tflite`,
  `spectrostream_decoder_core_fp16_f75.tflite`,
  `spectrostream_decoder_core_fp16_f100.tflite`, `rvq_codebooks.f32`
  и `istft_window_f960.f32`. Эти файлы **не включены в Git**: экспортируйте
  их по [../docs/model-export.md](../docs/model-export.md) и скопируйте сюда.
- `assets/sage/` — `dec_w8a8.tflite` (SAGE rung 128, int8). Модель также
  **не включена в Git**; ссылка на исходный SAGE-проект и порядок подготовки —
  в [assets/sage/README.md](assets/sage/README.md). `demo.sage` уже включён.
  SAGE использует `com.google.ai.edge.litert:litert:2.3.0` и Kotlin 2.4.
- `android/app/src/main/jniLibs/arm64-v8a/` — `libspectrostream_decoder.so`
  из Android-сборки декодера и `libc++_shared.so` из соответствующего NDK.

Сборка нативного runtime описана в [../decoder_cpp/README.md](../decoder_cpp/README.md).
Иконки Android хранятся в `android/app/src/main/res/`.

## THREADS и CORES

`THREADS` — число worker-потоков TFLite/XNNPACK/LiteRT. Это не число ядер:
потоки планируются ОС на любых доступных CPU.

`CORES` — ограничение affinity для потока декодера и созданных им worker-потоков.
Выбираются старшие по номеру CPU (обычно производительные ядра); `8` означает
«все доступные CPU». Это не эксклюзивное резервирование ядер: Android и другие
потоки приложения по-прежнему могут использовать эти CPU. Обычно имеет смысл
`THREADS <= CORES`; при большем числе потоков они делят одни и те же ядра.

## Если используется другой трек

Приложение демонстрирует заранее подготовленный трек, а не произвольный
файловый плеер. Демотрек уже лежит в `assets/audio/demo.mp3`,
`assets/spectrostream/demo.sst` и `assets/sage/demo.sage`. Для своего трека
подготовьте MP3, SpectroStream SST и SAGE-контейнер и положите их с этими
именами; все три режима должны использовать один и тот же исходник.

В `lib/services/asset_installer.dart` длительность SST задана константой
`_sstDurationSeconds = 133.607625`; для своего демотрека её нужно согласовать
с `metadata.json`. При замене демонабора увеличьте `_assetRevision`, иначе
устройство может сохранить старые assets. Дополнительно очистите данные
приложения или переустановите его.

## Запуск

Команды из `client_android/`:

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```

Модели для сборки нужно подготовить заранее; см. раздел «Подготовка».
Общая структура проекта и расположение данных описаны в [../README.md](../README.md).
Подробности реализации и результаты экспериментов — в [client_report.md](client_report.md).

При смене Flutter SDK сначала выполните `flutter pub get`: сохранённый
`.dart_tool/package_config.json` может ссылаться на прежний SDK и вызывать
ошибки компиляции внутри Flutter, хотя `flutter analyze` проходит.
Не переносите `.dart_tool/` и `build/` между машинами.

Widget-тест проверяет наличие экрана; он не подтверждает реальное
воспроизведение, работу FFI или корректность Android APK. Текущие
[результаты проверки](../docs/validation.md) описывают эту границу.

Gradle Wrapper (`android/gradlew`, `android/gradlew.bat`,
`android/gradle/wrapper/gradle-wrapper.jar` и настройки wrapper) включён
в Git. `local.properties`, Gradle caches и результаты сборки остаются
локальными. Полная сборка Android из чистого клона пока не подтверждена.
