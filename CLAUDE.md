# Neural Codecs Client Runtime

Проект исследует клиентское CPU-декодирование Google SpectroStream из Magenta
RealTime: аудио 48 kHz stereo → токены SST → RVQ → LiteRT/XNNPACK → iSTFT → PCM.
Основные метрики: размер данных, bitrate, скорость запуска, real-time factor,
потребление CPU/RAM и потоковое воспроизведение.

Актуальная структура и команды запуска описаны в [README.md](README.md).

- `encoder_service/` — Python batch encoder, экспорт моделей и диагностика.
  Исходная модель: `ssv2_48k_stereo`, Magenta RealTime `v1_legacy`.
- `decoder_cpp/` — автономный C++20 runtime, CLI, C API, тесты и Android-скрипты.
- `client_android/` — Flutter-клиент с MP3/neural demo и сетевыми профилями.
- `decoder_cpp/docs/` — архитектура и спецификация SST-контейнера.
- `media/` — локальные исходные медиа, токены и контрольные WAV.
  Вход кодировщика: `media/data/input/`, выход: `media/data/encoded/`,
  контрольные WAV Python: `media/data/reconstructed/`.
- `models/`, `decoder_cpp/models/` — кеш исходной модели и экспортированные веса.
- `third_party/`, `decoder_cpp/third_party/` — скачанные внешние зависимости.

Медиа, модели, зависимости, окружения и сборки исключены из Git. Демофайлы
Flutter в `client_android/assets/` ссылаются на `media/client_android/`
относительными символическими ссылками. Иконки Android являются ресурсами
приложения и остаются в `res/`. Пустые каталоги-заготовки удалены; создавайте
новые каталоги вместе с содержимым.

Пути Python-скриптов вычисляются относительно `__file__`; не добавляйте
абсолютные пути к рабочей копии. Отчёты прошлых экспериментов сохраняются
рядом с кодом соответствующего компонента.

## Работа с треком

Порядок подготовки: [docs/setup.md](docs/setup.md), затем
[docs/roundtrip.md](docs/roundtrip.md); для C++ при отсутствии готовых assets —
[docs/model-export.md](docs/model-export.md). Фактически проверенные команды
и ограничения записаны в [docs/validation.md](docs/validation.md).

Для CPU установите `CUDA_VISIBLE_DEVICES=-1` после `source encoder_service/env.sh`.
Не считайте код завершения batch encoder достаточной проверкой: ошибки треков
записываются в `error.json`, а процесс может вернуть 0. Проверяйте metadata,
счётчики и файлы; используйте новый выходной каталог внутри `media/`.
Python verification декодирует токены текущего запуска; независимое чтение SST
проверяется через C++ CLI. q16/q32 в metadata — оценки, SST сохраняется q64.

Не переписывайте эталонный трек ради smoke-проверки. Не меняйте зависимости
на последние версии ради обхода ошибки установки без отдельной проверки.
Отчёты прошлых экспериментов могут описывать устаревшие ограничения.
