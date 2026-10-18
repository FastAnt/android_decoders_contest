# Neural Codecs

Эксперимент с Google SpectroStream из Magenta RealTime: аудио кодируется
в токены SST, затем декодируется на CPU в WAV или воспроизводится
Flutter-клиентом на Android. Рабочий формат аудио — 48 kHz stereo.
Это кодек с потерями: восстановленный WAV не совпадает побитово с оригиналом.

## С чего начать

1. [Подготовить окружение, зависимости и исходные веса](docs/setup.md).
2. [Сжать свой трек и восстановить его в Python и C++](docs/roundtrip.md).
3. При необходимости [экспортировать модели для C++](docs/model-export.md).
4. Для приложения перейти к [инструкции Flutter/Android](client_android/README.md).

[Результаты проверки](docs/validation.md) отделяют выполненные сценарии
от шагов, которые пока не проверены с чистого клона.
Для агентов также есть краткая точка входа [AGENTS.md](AGENTS.md).

## Что умеет проект

- `encoder_service/batch_encode.py` читает файл или каталог с WAV, MP3,
  FLAC, OGG, Opus, M4A, AAC; через FFmpeg приводит аудио к 48 kHz stereo
  и записывает SST, метаданные и каталог треков.
- `--verify-first` включает контрольное Python-декодирование новых треков;
  `--verify-depths` выбирает глубины RVQ 16, 32, 64.
- C++ CLI независимо читает SST, проверяет CRC и декодирует в PCM16 WAV
  с помощью TFLite/XNNPACK. Есть C API для Flutter FFI и потокового декодирования.
- Flutter-приложение сравнивает время запуска MP3 и нейронного аудио
  при разных сетевых профилях и настройках модели/CPU.

SST хранит токены, но не веса декодера. Для восстановления нужны совместимые
модель, RVQ codebooks и окно iSTFT. Текущий кодировщик сохраняет полный q64;
q16/q32 в метаданных — оценки передачи, а не отдельные созданные файлы.

## Структура

- `encoder_service/` — Python-кодировщик и экспортёры; [параметры CLI](encoder_service/README.md).
- `decoder_cpp/` — runtime, CLI, C API, тесты и Android-скрипты;
  [сборка и CLI](decoder_cpp/README.md), [архитектура](decoder_cpp/docs/architecture.md),
  [формат SST1](decoder_cpp/docs/sst_format.md).
- `client_android/` — Flutter-клиент.
- `docs/` — подготовка, полный цикл, экспорт, результаты проверки и контрольные суммы.
- `media/` — исходное аудио, SST, WAV, изображения, видео и презентация.
- `models/` — кеш исходных SavedModels Magenta.
- `decoder_cpp/models/` — экспортированные assets runtime.
- `third_party/`, `decoder_cpp/third_party/` — локальные внешние зависимости.

## Какие файлы есть в Git

В репозитории сохраняются исходники, конфигурация, документация, тесты,
иконки приложения и небольшой сгенерированный демотрек:
`client_android/assets/audio/demo.mp3`,
`client_android/assets/spectrostream/demo.sst` и
`client_android/assets/sage/demo.sage`.

Бинарные веса и экспортированные модели **не хранятся в Git**: исходные
SavedModels SpectroStream скачиваются с Hugging Face, а core-модели TFLite,
codebooks и окно iSTFT экспортируются по
[инструкции](docs/model-export.md) либо скачиваются отдельно. Ссылки и
контрольные суммы — в [models/README.md](models/README.md),
[docs/source-model.sha256](docs/source-model.sha256) и
[docs/runtime-assets.sha256](docs/runtime-assets.sha256).

Медиа, внешние checkout, окружения, сборки и готовые нативные библиотеки
исключены через `.gitignore`. Для кодирования в чистом клоне нужно установить
зависимости; для Android — также собрать нативный runtime и подготовить
модели по [подготовке](docs/setup.md).

```text
media/                      # локальные эксперименты, не в Git
├── images/                 # изображения
├── videos/                 # видео и записи экрана
├── presentation/           # слайды
├── data/
│   ├── input/              # вход кодировщика по умолчанию
│   ├── encoded/            # SST, metadata.json, catalog.json
│   └── reconstructed/      # контрольные WAV Python
└── reconstructed/
    ├── cpp/                # контрольные WAV Linux
    └── android/            # контрольные WAV Android
```

Демотрек для приложения лежит прямо в `client_android/assets/`; это
сгенерированный трек, а не внешняя символическая ссылка. Каталоги новых
экспериментов создавайте внутри `media/`.
Иконки Android остаются в `android/app/src/main/res/`.

## Отчёты экспериментов

`decoder_cpp/report.md`, `decoder_cpp/ANDROID_REPORT.md`,
`decoder_cpp/android_build_report.md`,
`decoder_cpp/android/results/ANDROID_DEVICE_REPORT.md` и
`client_android/client_report.md` описывают отдельные прошлые эксперименты.
Их ограничения и показатели могут относиться к более ранним версиям;
для текущих команд используйте руководства выше и [проверку](docs/validation.md).
