#pragma once

#include <cstdint>
#include <memory>
#include <string>

namespace spectrostream {

struct LiteRtConfig {
    int num_threads = 4;
    bool use_xnnpack = true;
    bool use_gpu = false;
};

class LiteRtRunner {
public:
    explicit LiteRtRunner(const std::string& model_path, LiteRtConfig config = {});
    ~LiteRtRunner();

    LiteRtRunner(const LiteRtRunner&) = delete;
    LiteRtRunner& operator=(const LiteRtRunner&) = delete;
    LiteRtRunner(LiteRtRunner&&) noexcept;
    LiteRtRunner& operator=(LiteRtRunner&&) noexcept;

    const float* invoke(const float* embeddings);

    int input_frames() const;
    int input_dim() const;
    int output_channels() const;
    int output_stft_frames() const;
    int output_freq_bins() const;
    int output_size() const;

    static constexpr int kEmbeddingDim = 256;
    static constexpr int kChannels = 2;
    static constexpr int kFreqBins = 481;
    static constexpr int kComplexParts = 2;
    static constexpr int kStftFramesPerCodecFrame = 4;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace spectrostream
