#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace spectrostream {

class RvqDequantizer {
public:
    static constexpr uint32_t kNumLayers = 64;
    static constexpr uint32_t kCodebookSize = 1024;
    static constexpr uint32_t kEmbeddingDim = 256;

    explicit RvqDequantizer(const std::string& codebook_path);
    ~RvqDequantizer();

    RvqDequantizer(const RvqDequantizer&) = delete;
    RvqDequantizer& operator=(const RvqDequantizer&) = delete;
    RvqDequantizer(RvqDequantizer&&) noexcept;
    RvqDequantizer& operator=(RvqDequantizer&&) noexcept;

    // Dequantize a block of frames. tokens is frame-major [frames * rvq_depth].
    // Output: [frames * kEmbeddingDim] contiguous float32.
    std::vector<float> dequantize(const uint16_t* tokens,
                                  uint32_t frame_count,
                                  uint32_t rvq_depth) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace spectrostream
