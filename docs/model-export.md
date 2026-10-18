# Подготовить модели для C++ и Flutter

Для восстановления SST runtime нужны согласованные core-модель TFLite,
RVQ codebooks и окно iSTFT. Исходные веса Magenta и пакет TensorFlow
нужны на этапе экспорта; готовый C++ runtime не использует Python.

## Готовый набор или собственный экспорт

Готовые core-модели f25/f75/f100 в FP32/FP16, codebooks и окно включены
в Git. Для стандартного C++-декодирования уже доступны в `decoder_cpp/models/`:

- `spectrostream_decoder_core_fp32_f25.tflite` — 142784864 bytes;
- `rvq_codebooks.f32` — 67108864 bytes;
- `istft_window_f960.f32` — 3840 bytes.

Проверьте исходный набор из этого проекта:

```bash
sha256sum -c docs/decoder-f25.sha256
```

Чистый клон содержит эти файлы и исходные веса Magenta; повторный экспорт
для запуска не нужен. Рецепт ниже оставлен для воспроизведения и изменения
моделей. При повторном экспорте байты TFLite могут отличаться: сохраняйте
собственный отчёт, контрольные суммы и результаты численной проверки.

В Git сохранены отчёты исходных экспортов
[f25](model-reports/decoder_core_export_f25.json),
[f75](model-reports/decoder_core_export_f75.json) и
[f100](model-reports/decoder_core_export_f100.json), а также
`runtime-assets.sha256` для всех шести имеющихся core-моделей, codebooks
и окна. В отчётах пути нормализованы относительно корня проекта.
Повторный экспорт f25 FP32 и FP16 дал те же SHA256, что включённые в Git файлы.
Промежуточные экспортированные SavedModels, ONNX и Flex-эксперименты
остаются локальными; основные исходные и runtime-веса сохранены в репозитории.

## 1. Подготовить SavedModels и codebooks

Выполните [установку Python и загрузку исходных весов](setup.md).
Все команды далее выполняются из корня репозитория.
Каталог `MODEL_DIR` должен быть новым или не содержать результатов предыдущего
экспорта. Пример экспорта в новый каталог без перезаписи включённых весов:

```bash
source encoder_service/.venv/bin/activate
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
export OMP_NUM_THREADS=4
export TF_NUM_INTRAOP_THREADS=4
export TF_NUM_INTEROP_THREADS=2
export MODEL_DIR="media/model-export-f25-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$MODEL_DIR"

python - <<'PY'
import os
from pathlib import Path
import tensorflow as tf
from magenta_rt import spectrostream
from encoder_service.export_decoder_assets import (
    create_input_spec,
    export_codebooks,
    export_wrapped_savedmodel,
)
from encoder_service.export_litert_assets import export_fixed_savedmodel, load_signature

models = Path(os.environ['MODEL_DIR']).resolve()
codec = spectrostream.SpectroStream(max_rvq_depth=64, lazy=True)
export_codebooks(codec, models)
export_wrapped_savedmodel(codec, models, create_input_spec(None), force=False)
model, input_key, output_key = load_signature(tf, models / 'decoder_savedmodel')
export_fixed_savedmodel(
    tf=tf,
    source_model=model,
    input_key=input_key,
    output_key=output_key,
    frames=25,
    destination=models / 'decoder_savedmodel_f25',
    force=False,
)
PY
```

Этот рецепт использует существующие функции экспортёров и создаёт
`rvq_codebooks.npy`, `rvq_codebooks.f32`, `rvq_codebooks.json`,
`decoder_savedmodel/` и `decoder_savedmodel_f25/`.
Он не выполняет необязательные ONNX- и Flex-конвертации.
Для повторения выберите новый `MODEL_DIR`; не добавляйте принудительную
перезапись к рабочим моделям без необходимости.

## 2. Экспортировать core и окно iSTFT

```bash
python encoder_service/export_litert_core_v3.py \
  --models-dir "$MODEL_DIR" \
  --frames 25 \
  --threads 4 \
  --runs 1
```

Создаются FP32 и FP16 core-модели, `decoder_core_savedmodel_f25/`,
`istft_window_f960.f32` с метаданными и `decoder_core_export_f25.json`.
`--runs 1` сокращает число измерений inference; для замеров используйте
большее число. Скрипт сам проверяет численное соответствие TensorFlow;
ожидается `FP32 validation PASSED` и завершение с кодом 0.

Вход core-модели FP32: `[1, 25, 256]` float32 embeddings.
Выход: `[1, 2, 100, 481, 2]` float32, real/imag STFT.
C++ выполняет iSTFT отдельно. Полная модель с выходом PCM или файл с Flex
операторами не являются заменой core-модели.

Проверка отчёта и SHA256 созданных моделей:

```bash
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ['MODEL_DIR'])
report = json.loads((root / 'decoder_core_export_f25.json').read_text())
for precision, model in report['models'].items():
    path = Path(model['path'])
    assert model['operator_mode'] == 'builtin_only'
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert digest == model['sha256']
    print(precision, path.name, path.stat().st_size, digest)
for filename in ['rvq_codebooks.f32', 'istft_window_f960.f32']:
    assert (root / filename).is_file()
PY
```

Теперь можно выполнить [C++-часть round-trip](roundtrip.md).
Если экспортировали в нестандартный каталог, передавайте его файлы
в `--model`, `--codebooks`, `--window` вместо стандартных путей.

## Другие модели и исследовательские скрипты

Для f75/f100 подготовьте фиксированный SavedModel тем же вызовом
`export_fixed_savedmodel`, заменив `frames` и имя каталога, затем запускайте
core-export с соответствующим `--frames`. Сначала проверьте f25;
дополнительные варианты нужны Flutter и отдельным экспериментам.

Полный CLI `export_decoder_assets.py` также конвертирует ONNX и требует
`tf2onnx`, `onnx`, `onnxruntime`, которых нет в основном frozen-списке.
В исследовательском окружении наблюдались версии 1.17.0, 1.22.0, 1.27.0
соответственно; для рекомендуемого выше пути эти пакеты не нужны.
CLI `export_litert_assets.py` после сохранения фиксированного SavedModel
пытается конвертировать полную модель с Complex/IRFFT и может использовать
Flex или завершиться на численной проверке. Поэтому основной рецепт
вызывает только его функцию подготовки SavedModel.

Старые `export_litert_core.py` и `export_litert_core_v2.py` — предыдущие
эксперименты. ONNX-модель, полная TFLite/Flex-модель и builtin-only core
имеют разные контракты и не взаимозаменяемы.

[Проверенные шаги и ограничения](validation.md).
