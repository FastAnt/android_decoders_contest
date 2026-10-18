#include "spectrostream/rvq_dequantizer.h"

#include <cstdio>
#include <cstring>
#include <stdexcept>

namespace spectrostream {

struct RvqDequantizer::Impl {
    // codebooks_[layer * kCodebookSize * kEmbeddingDim + entry * kEmbeddingDim + dim]
    std::vector<float> codebooks;
};

RvqDequantizer::RvqDequantizer(const std::string& codebook_path) : impl_(std::make_unique<Impl>()) {
    const size_t expected_floats =
        static_cast<size_t>(kNumLayers) * kCodebookSize * kEmbeddingDim;
    const size_t expected_bytes = expected_floats * sizeof(float);

    FILE* f = std::fopen(codebook_path.c_str(), "rb");
    if (!f) throw std::runtime_error("Cannot open codebook file: " + codebook_path);

    std::fseek(f, 0, SEEK_END);
    long file_size = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);

    if (static_cast<size_t>(file_size) != expected_bytes) {
        std::fclose(f);
        throw std::runtime_error(
            "Codebook file size mismatch: expected " + std::to_string(expected_bytes) +
            " bytes, got " + std::to_string(file_size));
    }

    impl_->codebooks.resize(expected_floats);
    size_t read = std::fread(impl_->codebooks.data(), sizeof(float), expected_floats, f);
    std::fclose(f);

    if (read != expected_floats) {
        throw std::runtime_error("Short read on codebook file");
    }
}

RvqDequantizer::~RvqDequantizer() = default;
RvqDequantizer::RvqDequantizer(RvqDequantizer&&) noexcept = default;
RvqDequantizer& RvqDequantizer::operator=(RvqDequantizer&&) noexcept = default;

std::vector<float> RvqDequantizer::dequantize(const uint16_t* tokens,
                                               uint32_t frame_count,
                                               uint32_t rvq_depth) const {
    if (rvq_depth > kNumLayers) {
        throw std::runtime_error("RVQ depth exceeds maximum: " + std::to_string(rvq_depth));
    }

    const size_t out_size = static_cast<size_t>(frame_count) * kEmbeddingDim;
    std::vector<float> embeddings(out_size, 0.0f);

    const float* cb = impl_->codebooks.data();
    const size_t layer_stride = static_cast<size_t>(kCodebookSize) * kEmbeddingDim;

    for (uint32_t frame = 0; frame < frame_count; ++frame) {
        float* emb = embeddings.data() + static_cast<size_t>(frame) * kEmbeddingDim;
        const uint16_t* frame_tokens = tokens + static_cast<size_t>(frame) * rvq_depth;

        for (uint32_t d = 0; d < rvq_depth; ++d) {
            uint16_t idx = frame_tokens[d];
            if (idx >= kCodebookSize) {
                throw std::runtime_error("Token index out of range: " + std::to_string(idx));
            }
            const float* entry = cb + d * layer_stride + static_cast<size_t>(idx) * kEmbeddingDim;
            for (uint32_t dim = 0; dim < kEmbeddingDim; ++dim) {
                emb[dim] += entry[dim];
            }
        }
    }

    return embeddings;
}

}  // namespace spectrostream
