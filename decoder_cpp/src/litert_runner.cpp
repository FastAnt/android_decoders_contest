#include "spectrostream/litert_runner.h"

#include <cstring>
#include <stdexcept>
#include <string>

#include "tensorflow/lite/interpreter.h"
#include "tensorflow/lite/kernels/register.h"
#include "tensorflow/lite/model.h"
#include "tensorflow/lite/delegates/xnnpack/xnnpack_delegate.h"

#if SS_ENABLE_GPU_DELEGATE
#include "tensorflow/lite/delegates/gpu/delegate.h"
#endif

namespace spectrostream {

struct LiteRtRunner::Impl {
    std::unique_ptr<tflite::FlatBufferModel> model;
    std::unique_ptr<tflite::Interpreter> interpreter;
    TfLiteDelegate* xnnpack_delegate = nullptr;
#if SS_ENABLE_GPU_DELEGATE
    TfLiteDelegate* gpu_delegate = nullptr;
#endif
    int input_tensor_index = -1;
    int output_tensor_index = -1;
    int input_frames = 0;
    int input_dim = 0;
    int out_channels = 0;
    int out_stft_frames = 0;
    int out_freq_bins = 0;
    int out_size = 0;
    bool using_gpu = false;
};

LiteRtRunner::LiteRtRunner(const std::string& model_path, LiteRtConfig config)
    : impl_(std::make_unique<Impl>()) {

    impl_->model = tflite::FlatBufferModel::BuildFromFile(model_path.c_str());
    if (!impl_->model) {
        throw std::runtime_error("Failed to load TFLite model: " + model_path);
    }

    tflite::ops::builtin::BuiltinOpResolver resolver;
    tflite::InterpreterBuilder builder(*impl_->model, resolver);
    builder.SetNumThreads(config.num_threads);

    if (builder(&impl_->interpreter) != kTfLiteOk || !impl_->interpreter) {
        throw std::runtime_error("Failed to build TFLite interpreter");
    }

    bool delegate_applied = false;

#if SS_ENABLE_GPU_DELEGATE
    if (config.use_gpu) {
        TfLiteGpuDelegateOptionsV2 gpu_opts = TfLiteGpuDelegateOptionsV2Default();
        gpu_opts.inference_preference = TFLITE_GPU_INFERENCE_PREFERENCE_SUSTAINED_SPEED;
        gpu_opts.inference_priority1 = TFLITE_GPU_INFERENCE_PRIORITY_MIN_LATENCY;
        gpu_opts.inference_priority2 = TFLITE_GPU_INFERENCE_PRIORITY_MIN_MEMORY_USAGE;
        gpu_opts.inference_priority3 = TFLITE_GPU_INFERENCE_PRIORITY_MAX_PRECISION;
        impl_->gpu_delegate = TfLiteGpuDelegateV2Create(&gpu_opts);
        if (impl_->gpu_delegate) {
            if (impl_->interpreter->ModifyGraphWithDelegate(impl_->gpu_delegate) == kTfLiteOk) {
                delegate_applied = true;
                impl_->using_gpu = true;
            } else {
                TfLiteGpuDelegateV2Delete(impl_->gpu_delegate);
                impl_->gpu_delegate = nullptr;
            }
        }
    }
#endif

    if (!delegate_applied && config.use_xnnpack) {
        TfLiteXNNPackDelegateOptions xnnpack_opts = TfLiteXNNPackDelegateOptionsDefault();
        xnnpack_opts.num_threads = config.num_threads;
        impl_->xnnpack_delegate = TfLiteXNNPackDelegateCreate(&xnnpack_opts);
        if (impl_->interpreter->ModifyGraphWithDelegate(impl_->xnnpack_delegate) != kTfLiteOk) {
            TfLiteXNNPackDelegateDelete(impl_->xnnpack_delegate);
            impl_->xnnpack_delegate = nullptr;
        }
    }

    if (impl_->interpreter->AllocateTensors() != kTfLiteOk) {
        throw std::runtime_error("Failed to allocate TFLite tensors");
    }

    // Validate input: [1, frames, 256]
    auto inputs = impl_->interpreter->inputs();
    if (inputs.size() != 1) {
        throw std::runtime_error("Expected 1 input tensor, got " + std::to_string(inputs.size()));
    }
    impl_->input_tensor_index = inputs[0];

    TfLiteTensor* input_tensor = impl_->interpreter->tensor(impl_->input_tensor_index);
    if (input_tensor->type != kTfLiteFloat32) {
        throw std::runtime_error("Input tensor is not float32");
    }
    if (input_tensor->dims->size != 3 || input_tensor->dims->data[0] != 1) {
        throw std::runtime_error("Input tensor must be [1, frames, dim]");
    }
    impl_->input_frames = input_tensor->dims->data[1];
    impl_->input_dim = input_tensor->dims->data[2];

    if (impl_->input_dim != kEmbeddingDim) {
        throw std::runtime_error("Input dim mismatch: got " + std::to_string(impl_->input_dim) +
                                 ", expected " + std::to_string(kEmbeddingDim));
    }

    // Validate output: [1, 2, stft_frames, 481, 2]
    auto outputs = impl_->interpreter->outputs();
    if (outputs.size() != 1) {
        throw std::runtime_error("Expected 1 output tensor, got " + std::to_string(outputs.size()));
    }
    impl_->output_tensor_index = outputs[0];

    TfLiteTensor* output_tensor = impl_->interpreter->tensor(impl_->output_tensor_index);
    if (output_tensor->type != kTfLiteFloat32) {
        throw std::runtime_error("Output tensor is not float32");
    }
    if (output_tensor->dims->size != 5 || output_tensor->dims->data[0] != 1) {
        throw std::runtime_error("Output tensor must be [1, channels, stft_frames, freq_bins, 2]");
    }

    impl_->out_channels = output_tensor->dims->data[1];
    impl_->out_stft_frames = output_tensor->dims->data[2];
    impl_->out_freq_bins = output_tensor->dims->data[3];
    int complex_parts = output_tensor->dims->data[4];

    if (impl_->out_channels != kChannels) {
        throw std::runtime_error("Output channels: " + std::to_string(impl_->out_channels));
    }
    if (impl_->out_freq_bins != kFreqBins) {
        throw std::runtime_error("Output freq bins: " + std::to_string(impl_->out_freq_bins));
    }
    if (complex_parts != kComplexParts) {
        throw std::runtime_error("Output complex parts: " + std::to_string(complex_parts));
    }

    // Verify stft_frames == input_frames * 4
    int expected_stft = impl_->input_frames * kStftFramesPerCodecFrame;
    if (impl_->out_stft_frames != expected_stft) {
        throw std::runtime_error("STFT frames mismatch: got " + std::to_string(impl_->out_stft_frames) +
                                 ", expected " + std::to_string(expected_stft));
    }

    impl_->out_size = impl_->out_channels * impl_->out_stft_frames *
                      impl_->out_freq_bins * kComplexParts;
}

LiteRtRunner::~LiteRtRunner() {
    if (impl_) {
        if (impl_->xnnpack_delegate) {
            TfLiteXNNPackDelegateDelete(impl_->xnnpack_delegate);
        }
#if SS_ENABLE_GPU_DELEGATE
        if (impl_->gpu_delegate) {
            TfLiteGpuDelegateV2Delete(impl_->gpu_delegate);
        }
#endif
    }
}

LiteRtRunner::LiteRtRunner(LiteRtRunner&&) noexcept = default;
LiteRtRunner& LiteRtRunner::operator=(LiteRtRunner&&) noexcept = default;

const float* LiteRtRunner::invoke(const float* embeddings) {
    float* input_data = impl_->interpreter->typed_tensor<float>(impl_->input_tensor_index);
    std::memcpy(input_data, embeddings,
                static_cast<size_t>(impl_->input_frames) * impl_->input_dim * sizeof(float));

    if (impl_->interpreter->Invoke() != kTfLiteOk) {
        throw std::runtime_error("TFLite inference failed");
    }

    return impl_->interpreter->typed_tensor<float>(impl_->output_tensor_index);
}

int LiteRtRunner::input_frames() const { return impl_->input_frames; }
int LiteRtRunner::input_dim() const { return impl_->input_dim; }
int LiteRtRunner::output_channels() const { return impl_->out_channels; }
int LiteRtRunner::output_stft_frames() const { return impl_->out_stft_frames; }
int LiteRtRunner::output_freq_bins() const { return impl_->out_freq_bins; }
int LiteRtRunner::output_size() const { return impl_->out_size; }

}  // namespace spectrostream
