# Сжать трек и восстановить WAV

Сценарий: файл → FFmpeg → SpectroStream → SST → независимый C++ decoder → WAV.
Параллельно можно получить контрольный WAV в Python. Кодек работает с потерями;
выход — PCM16, 48000 Hz, stereo. Равенства байтов исходнику не ожидается.

## 1. Выбрать трек и подготовить процесс

Сначала выполните [подготовку Python и исходных весов](setup.md).
Все блоки ниже выполняются из корня репозитория в одной Bash-сессии.
Замените только `INPUT` своим путём; демофайл не включён в Git.

```bash
source encoder_service/.venv/bin/activate
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
export OMP_NUM_THREADS=4
export TF_NUM_INTRAOP_THREADS=4
export TF_NUM_INTEROP_THREADS=2

INPUT="/абсолютный/путь/к/треку.mp3"
RUN_DIR="media/roundtrip-$(date +%Y%m%d-%H%M%S)"
test -f "$INPUT"
mkdir -p "$RUN_DIR"
```

Значение `CUDA_VISIBLE_DEVICES=-1` задавайте после `source env.sh`.
Остальные три переменные ограничивают число CPU-потоков для этого запуска.
Для проверки на существующем локальном демотреке можно задать
`INPUT="$PWD/media/client_android/demo.mp3"`.

## 2. Закодировать и получить контрольный WAV Python

```bash
python encoder_service/batch_encode.py \
  --input "$INPUT" \
  --output "$RUN_DIR/encoded" \
  --reconstructed "$RUN_DIR/python" \
  --device cpu \
  --verify-first 1 \
  --verify-depths 64
```

Для первого короткого прогона добавьте `--max-seconds 3`; без этого параметра
кодируется весь трек. Загрузка модели и прогрев могут занять больше времени,
чем обработка короткого фрагмента.

Создаются:

```text
RUN_DIR/
├── encoded/
│   ├── catalog.json
│   └── TRACK_ID/
│       ├── TRACK_ID.sst
│       └── metadata.json
└── python/
    └── TRACK_ID/
        └── TRACK_ID.q64.wav
```

Если имя исходника заканчивается 32-символьным hex ID, используется этот ID;
иначе ID вычисляется из абсолютного пути. Перенос исходника может поменять ID.
Не подставляйте идентификатор демонстрационного трека в команды для своего аудио.

`--verify-first 1` декодирует токены первого **вновь закодированного** трека
в текущем процессе; этот этап не читает SST с диска. Независимое чтение SST
проверяется шагом C++ ниже. Без `--verify-first` WAV Python не создаётся.

При повторном запуске в тот же выходной каталог уже обработанный файл может
быть пропущен. Чтобы перекодировать его и повторить проверку, добавьте `--force`.
Изменение только `--verify-depths` или `--verify-first` не отменяет пропуск.

## 3. Проверить успех и найти SST

Кодировщик ловит ошибки отдельных треков и записывает `error.json`;
**код завершения 0 сам по себе не означает успешное кодирование**.
Должны совпасть итоговые счётчики, метаданные и фактические файлы.
Следующая команда ожидает один трек в новом выходном каталоге:

```bash
SST_FILE="$(python - "$RUN_DIR/encoded/catalog.json" <<'PY'
import json
import sys
from pathlib import Path

catalog = json.loads(Path(sys.argv[1]).read_text())
assert catalog['track_count'] == 1, 'Ожидался один успешно закодированный трек'
track = catalog['tracks'][0]
assert track['status'] == 'success' and track['container_validated']
assert len(track['verifications']) == 1, 'Нет контрольного декодирования'
sst = Path(track['container_path'])
assert sst.is_file() and sst.stat().st_size == track['container_bytes']
assert Path(track['verifications'][0]['file']).is_file()
assert not (sst.parent / 'error.json').exists(), 'Есть ошибка последнего запуска'
print(sst)
PY
)"
test -f "$SST_FILE"
```

При ошибке не переходите к декодированию: проверьте вывод `FAILED`,
`Failed in this run` и `encoded/TRACK_ID/error.json`. Старые metadata/catalog
могут остаться от предыдущих запусков; новый `RUN_DIR` устраняет эту неоднозначность.

## 4. Независимо декодировать SST в C++

Требуются собранный runtime из [setup](setup.md) и три согласованных файла
из [инструкции экспорта](model-export.md). Для подготовленного локального
набора проверьте их контрольные суммы:

```bash
sha256sum -c docs/decoder-f25.sha256
decoder_cpp/build/spectrostream_decode --inspect --input "$SST_FILE"

decoder_cpp/build/spectrostream_decode \
  --model decoder_cpp/models/spectrostream_decoder_core_fp32_f25.tflite \
  --codebooks decoder_cpp/models/rvq_codebooks.f32 \
  --window decoder_cpp/models/istft_window_f960.f32 \
  --input "$SST_FILE" \
  --output "$RUN_DIR/cpp.wav" \
  --threads 4
```

`--inspect` не требует моделей и проверяет заголовок, диапазон токенов и CRC;
ожидается `CRC status: OK`. Полное декодирование требует весов и завершения
с кодом 0. SHA256 выше относится к передаваемому исходному набору: собственный
повторный экспорт проверяйте по созданному им отчёту, байты могут отличаться.

## 5. Проверить WAV

```bash
python - "$RUN_DIR/encoded/catalog.json" "$RUN_DIR/cpp.wav" <<'PY'
import json
import sys
import wave
from pathlib import Path

track = json.loads(Path(sys.argv[1]).read_text())['tracks'][0]
for name in [track['verifications'][0]['file'], sys.argv[2]]:
    with wave.open(name) as wav:
        assert wav.getframerate() == 48000
        assert wav.getnchannels() == 2
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == track['original_samples']
        print(name, wav.getnframes() / wav.getframerate(), 'seconds, PCM16 stereo')
PY
```

Проверка подтверждает формат и длину, но не измеряет качество звука.
Python и C++ используют разные схемы блочного декодирования, поэтому
побитового совпадения между их WAV также не требуется.
Для визуальной проверки заголовка можно использовать `ffprobe`:

```bash
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels \
  -show_entries format=duration,size -of json "$RUN_DIR/cpp.wav"
```

Файл SST содержит полный q64: номинально 16 kbit/s плюс заголовки.
`stream_variants.q16/q32` в metadata — оценки размеров передачи при 4/8 kbit/s;
`--verify-depths 16,32,64` создаёт варианты WAV, а не три разных SST.
При `--max-seconds` не сравнивайте размер короткого SST с размером всего MP3
как степень сжатия одного и того же фрагмента.

## Повторение и передача результата

Сохраните команды, metadata/catalog, лог CLI, версии инструментов и контрольные
суммы модели/codebooks/window. Метаданные содержат абсолютные пути; после
переноса данных проверьте их актуальность. Медиа передаются отдельно
от Git; исходные и runtime-веса уже включены в репозиторий и bundle.
Текущие [результаты прогона](validation.md) показывают выполненные проверки.
