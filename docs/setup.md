# Подготовка из чистого клона

Все команды выполняются в Bash из корня репозитория на Linux.
Проверенное существующее окружение: Ubuntu 24.04 x86-64, Python 3.12.3,
TensorFlow 2.20.0, NumPy 2.4.6, GCC 13.3, CMake 3.28.3, FFmpeg 6.1.1.
Свежая установка всех пакетов и загрузка зависимостей с нуля отдельно
не повторялись; [границы проверки](validation.md) указаны явно.

## 1. Системные инструменты

Нужны Git, Python 3.12 с `venv`, FFmpeg/ffprobe. Для сборки C++ также нужны
CMake 3.22+ и C++20-компилятор; Ninja можно использовать как альтернативу Make.
Установите эти инструменты средствами своей ОС. Для полного Python-пути
кеш исходных весов занимает около 484 MiB, а окружение с зависимостями —
несколько GiB; C++-сборка и экспорт добавляют дополнительные GiB.

## 2. Python-окружение

```bash
python3.12 -m venv encoder_service/.venv
source encoder_service/.venv/bin/activate
python -m pip install -r encoder_service/requirements.lock.txt
python -m pip check
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
```

Список зависимостей закрепляет Magenta RealTime на ревизии
`04ebaa7da13701734281c630ffd13f7ee9893e45` (`v1_legacy`, пакет `magenta_rt` 0.3.0).
Отдельный checkout в `third_party/magenta-realtime/` не обязателен:
`pip` установит зафиксированную editable-зависимость из Git.
Не заменяйте эту ревизию текущей веткой upstream без отдельной проверки.

`env.sh` **сбрасывает** `CUDA_VISIBLE_DEVICES`; поэтому CPU-переменную
нужно задавать **после** подключения файла. На машине с GPU комбинация
`--device cpu` без этой переменной может завершиться ошибкой
`Physical devices cannot be modified after being initialized`: Magenta
пытается менять GPU memory growth после инициализации TensorFlow.
Для GPU-запуска переменную `-1` не задавайте; GPU-сценарий здесь не проверен.

Проверка импорта ещё не загружает веса:

```bash
python -c 'import tensorflow as tf; from magenta_rt import spectrostream; print(tf.__version__)'
ffmpeg -version
```

## 3. Исходные веса SpectroStream

Magenta использует `encoder`, `decoder` и `quantizer` из `ssv2_48k_stereo`.
Сами SavedModel **не включены в Git**: их нужно скачать с Hugging Face.
Ссылки, закреплённая ревизия и лицензия — в
[models/README.md](../models/README.md). После загрузки проверьте целостность:

```bash
sha256sum -c docs/source-model.sha256
```

Если проверка проходит, переходите к round-trip.
По умолчанию `env.sh` задаёт источник `hf` и корень кеша
`models/magenta_rt_cache/`. При первом запуске Magenta может получить
отсутствующие модели самостоятельно, но этот путь не закрепляет ревизию весов.

Для повторного получения утраченных весов или другого рабочего каталога
используйте ревизию Hugging Face, записанную в метаданных исходного кеша:

```bash
python - <<'PY'
import os
from pathlib import Path
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id='google/magenta-realtime',
    revision='c05f8d6d608afd588469b7a8ef0929d5a1f8f6bb',
    allow_patterns=['savedmodels/ssv2_48k_stereo/**'],
    local_dir=Path(os.environ['MAGENTA_RT_CACHE_DIR']) / 'assets',
)
PY
sha256sum -c docs/source-model.sha256
```

Ожидаемая структура: `models/magenta_rt_cache/assets/savedmodels/ssv2_48k_stereo/`,
внутри — `encoder/`, `decoder/`, `quantizer/` с SavedModel и переменными.
Можно перенести этот полный каталог из подготовленного окружения вместо
повторной загрузки. Проверка checksum выше использует стандартное расположение.

Для другого кеша задайте `MAGENTA_RT_CACHE_DIR` до подключения `env.sh`.
Переменные кеша и источника должны быть установлены до импорта Magenta.
Не создавайте пустые каталоги моделей вручную: Magenta может принять
существующий каталог за уже загруженный asset.

После этого доступен [Python round-trip](roundtrip.md). C++ и Android
для него не нужны.

## 4. Зависимости C++ — при необходимости

TensorFlow Lite **не скачивается автоматически**: CMake ожидает локальные
исходники TensorFlow. Подтверждённая локальная версия — v2.18.0,
commit `6550e4bd80223cdb8be6c3afd1f81e86a4d433c3`.
Версия Python TensorFlow при этом 2.20.0 — это разные компоненты.

На чистом клоне:

```bash
mkdir -p decoder_cpp/third_party
git clone --branch v2.18.0 --depth 1 \
  https://github.com/tensorflow/tensorflow.git \
  decoder_cpp/third_party/tensorflow
test "$(git -C decoder_cpp/third_party/tensorflow rev-parse HEAD)" = \
  6550e4bd80223cdb8be6c3afd1f81e86a4d433c3
```

CMake скачивает дополнительные зависимости, включая PocketFFT. В CMake
PocketFFT привязан к ветке `cpp`; наблюдаемая рабочая ревизия —
`c90e55b3d529f8efa40ed01a20de22405f45fc65`. Для явного закрепления:

```bash
git clone https://github.com/mreineck/pocketfft.git \
  decoder_cpp/third_party/pocketfft
git -C decoder_cpp/third_party/pocketfft checkout --detach \
  c90e55b3d529f8efa40ed01a20de22405f45fc65
cmake -S decoder_cpp -B decoder_cpp/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DFETCHCONTENT_SOURCE_DIR_POCKETFFT="$PWD/decoder_cpp/third_party/pocketfft"
cmake --build decoder_cpp/build -j4
```

Для уже настроенной рабочей копии достаточно обычных команд сборки из
[README декодера](../decoder_cpp/README.md). Исходники в `third_party/`
исключены из Git. Для декодирования также нужны
[экспортированные assets](model-export.md) — они **не включены в Git**,
а сборка C++ их не создаёт. Их нужно экспортировать или скачать отдельно.

Контрольные суммы исходного набора весов и runtime assets сохранены для
проверки после загрузки: `docs/source-model.sha256`,
`docs/runtime-assets.sha256` и `docs/packaged-weights.sha256`.
