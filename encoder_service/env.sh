unset CUDA_VISIBLE_DEVICES

export TF_CPP_MIN_LOG_LEVEL=1
export TF_FORCE_GPU_ALLOW_GROWTH=true
export TF_GPU_ALLOCATOR=cuda_malloc_async
export XLA_PYTHON_CLIENT_PREALLOCATE=false

export MAGENTA_RT_DEFAULT_ASSET_SOURCE=hf
export MAGENTA_RT_CACHE_DIR="${MAGENTA_RT_CACHE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/models/magenta_rt_cache}"
