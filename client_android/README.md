# Neural Codecs Android Client

Flutter-приложение для сравнения времени запуска MP3 и SpectroStream.
Нейронное аудио декодируется через `dart:ffi` и C++ runtime; в приложении
доступны сетевые профили, выбор модели и числа потоков CPU.

## Подготовка

Нужны Flutter с Dart SDK, совместимым с `pubspec.yaml` (`^3.10.7`), Android SDK,
NDK и устройство или эмулятор `arm64-v8a` с Android API 26+.
Проверка widget-теста выполнена на Flutter 3.44.8 / Dart 3.12.2;
исходный lockfile создан другим SDK. `flutter pub get` на новом SDK может
обновить зависимости, закреплённые самим Flutter; такие изменения проверяйте
и фиксируйте отдельно от изменения документации.

Перед запуском восстановите локальные ресурсы, исключённые из Git:

- `../media/client_android/demo.mp3` и `demo.sst` — демотрек и его токены.
  Файлы в `assets/audio/demo.mp3` и `assets/spectrostream/demo.sst`
  являются относительными символическими ссылками на эти медиа.
- `assets/spectrostream/` — `spectrostream_decoder_core_fp32_f25.tflite`,
  `spectrostream_decoder_core_fp32_f75.tflite`,
  `spectrostream_decoder_core_fp16_f25.tflite`,
  `spectrostream_decoder_core_fp16_f75.tflite`,
  `spectrostream_decoder_core_fp16_f100.tflite`, `rvq_codebooks.f32`
  и `istft_window_f960.f32` из `../decoder_cpp/models/`.
- `android/app/src/main/jniLibs/arm64-v8a/` — `libspectrostream_decoder.so`
  из Android-сборки декодера и `libc++_shared.so` из соответствующего NDK.

Сборка нативного runtime описана в [../decoder_cpp/README.md](../decoder_cpp/README.md).
Иконки Android хранятся в `android/app/src/main/res/`.

## Если используется другой трек

Приложение демонстрирует заранее подготовленный трек, а не произвольный
файловый плеер. Сначала выполните [round-trip](../docs/roundtrip.md),
затем поместите соответствующие MP3 и SST в `../media/client_android/`
под именами `demo.mp3` и `demo.sst`. Если исходник не MP3, подготовьте MP3
через FFmpeg и кодируйте именно эту версию для сравнения одного материала.

В `lib/services/asset_installer.dart` длительность SST сейчас задана
константой `_sstDurationSeconds = 162.075`; для своего демотрека её нужно
согласовать с `metadata.json`. Иначе расчёт передачи первого блока будет
неверным. Assets на устройстве кешируются: при замене демонабора очистите
данные приложения или переустановите его, чтобы исключить старые файлы.

## Запуск

Команды из `client_android/`:

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```

Убедитесь, что при переносе проекта сохраняются символические ссылки.
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
