# Python encoder и экспорт SpectroStream

[Подготовка окружения и весов](../docs/setup.md) ·
[Полный цикл на своём треке](../docs/roundtrip.md) ·
[Экспорт assets C++](../docs/model-export.md)

Все примеры выполняются из корня репозитория. Скрипты вычисляют стандартные
каталоги относительно `__file__`; аргументы путей CLI — относительно текущего
каталога запуска. Не запускайте повторное кодирование в каталоге эталонной
фикстуры, если не собираетесь её заменять.

## batch_encode.py

Вход — файл либо рекурсивно просматриваемый каталог с расширениями
`.wav`, `.wave`, `.mp3`, `.flac`, `.ogg`, `.opus`, `.m4a`, `.aac`.
FFmpeg преобразует аудио в float32 PCM 48000 Hz stereo.
Кодирование использует RVQ depth 64 и пишет SST1 с 10-битными токенами.

Основные параметры:

- `--input PATH` — файл/каталог; стандартно `media/data/input/`.
- `--output DIR` — SST и метаданные; стандартно `media/data/encoded/`.
- `--reconstructed DIR` — контрольные WAV; стандартно `media/data/reconstructed/`.
- `--device cpu|gpu|auto` — стандартно `gpu`; для CPU на GPU-машине также
  установите `CUDA_VISIBLE_DEVICES=-1` после `source encoder_service/env.sh`.
- `--max-seconds N` — ограничить каждый трек первыми N секундами.
- `--limit N` — обработать первые N найденных файлов.
- `--verify-first N` — восстановить первые N новых треков; стандартно 0.
- `--verify-depths 16,32,64` — глубины контрольного декодирования;
  допустимы только 16, 32, 64, стандартно все три.
- `--force` — повторно обработать ранее закодированные файлы.
- `--inference-chunk-seconds N` — центральный фрагмент inference, стандартно 8 s.
- `--context-seconds N` — контекст с каждой стороны, стандартно 1 s.

Контейнер разбит на чанки по 25 codec frames (1 s) с отдельными CRC.
Это отдельное понятие от 8-секундных inference-фрагментов.

```bash
source encoder_service/.venv/bin/activate
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
python encoder_service/batch_encode.py --help
```

Для пакетной обработки передайте собственный каталог в `--input`.
Одинаковый 32-символьный ID в именах MP3 и WAV даёт одинаковый выходной ID;
не кладите альтернативные версии одного трека в пакет без учёта этого правила.

## Как определить успешную обработку

Успешный трек имеет `metadata.json` со `status: success` и
`container_validated: true`, фактический SST и запись в `catalog.json`.
Ошибки треков записываются в `error.json`; процесс может завершиться кодом 0
при наличии ошибок. Проверяйте `Failed in this run` и созданные файлы.
Каталог с данными прошлых запусков может содержать устаревшие успешные записи.

Кодировщик пропускает подходящие готовые результаты. Изменение только
`--verify-first`/`--verify-depths` не запускает обработку заново; нужен `--force`
или новый каталог выхода. Варианты q16/q32 в metadata — расчётные оценки,
а записанный SST остаётся q64.

## Экспорт и диагностика

Рекомендуемый путь описан в [model-export.md](../docs/model-export.md).
`export_litert_core_v3.py` создаёт core-модели для C++/Flutter.
`export_decoder_assets.py` и `export_litert_assets.py` также содержат
вспомогательные функции для подготовки SavedModel и codebooks.

Самостоятельные ONNX/Flex-эксперименты (`diagnose_onnx_decoder.py`,
`export_decoder_assets.py` как CLI, полный CLI `export_litert_assets.py`)
не обязательны для основного C++-пути. Старые `export_litert_core.py` и
`export_litert_core_v2.py` сохранены для воспроизведения исследований;
не выбирайте их как основной экспортёр для нового запуска.
