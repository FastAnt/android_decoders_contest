#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace spectrostream {

struct SstFileHeader {
    uint32_t sample_rate;
    uint16_t channels;
    uint16_t frame_rate;
    uint16_t max_rvq_depth;
    uint16_t bits_per_code;
    uint32_t chunk_frames;
    uint32_t total_frame_count;
    uint64_t original_samples;
    uint32_t chunk_count;
    uint32_t layout;
};

struct TokenStream {
    uint32_t sample_rate;
    uint32_t codec_frame_rate;
    uint32_t frame_count;
    uint32_t rvq_depth;
    uint64_t original_samples;

    // Frame-major: tokens[frame * rvq_depth + depth]
    std::vector<uint16_t> tokens;

    uint16_t token_at(uint32_t frame, uint32_t depth) const {
        return tokens[static_cast<size_t>(frame) * rvq_depth + depth];
    }
};

struct SstInspectResult {
    SstFileHeader header;
    uint32_t total_payload_bytes;
    uint16_t min_token;
    uint16_t max_token;
    bool all_crcs_valid;
    double duration_seconds;
};

TokenStream read_sst(const std::string& path);

SstInspectResult inspect_sst(const std::string& path);

}  // namespace spectrostream
