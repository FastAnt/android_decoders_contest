#include "spectrostream/sst_reader.h"

#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>

namespace spectrostream {
namespace {

constexpr uint32_t kMagic = 0x31545353;  // "SST1" as little-endian uint32
constexpr uint16_t kVersion = 1;
constexpr uint16_t kHeaderSize = 64;
constexpr uint32_t kLayoutCodebookMajor = 1;

#pragma pack(push, 1)
struct RawFileHeader {
    char magic[4];
    uint16_t version;
    uint16_t header_size;
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
    uint8_t reserved[20];
};
static_assert(sizeof(RawFileHeader) == 64);

struct RawChunkHeader {
    uint16_t frames_in_chunk;
    uint16_t stored_rvq_depth;
    uint32_t payload_bytes;
    uint32_t payload_crc32;
    uint32_t reserved;
};
static_assert(sizeof(RawChunkHeader) == 16);
#pragma pack(pop)

uint32_t crc32(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int j = 0; j < 8; ++j) {
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
        }
    }
    return ~crc;
}

uint32_t expected_payload_bytes(uint32_t frame_count, uint32_t rvq_depth, uint32_t bits_per_code) {
    uint64_t total_bits = static_cast<uint64_t>(frame_count) * rvq_depth * bits_per_code;
    return static_cast<uint32_t>((total_bits + 7) / 8);
}

// Unpack 10-bit values from little-endian bitstream.
// The tokens are stored codebook-major: [depth][frames] flattened, then packed.
// We need to unpack and transpose to frame-major: [frames][depth].
void unpack_10bit_codebook_major(const uint8_t* packed, uint32_t total_values,
                                  uint32_t frames, uint32_t depth,
                                  uint16_t* out_frame_major) {
    // Unpack all values sequentially (codebook-major order)
    std::vector<uint16_t> linear(total_values);

    uint64_t bit_offset = 0;
    for (uint32_t i = 0; i < total_values; ++i) {
        uint32_t byte_idx = static_cast<uint32_t>(bit_offset / 8);
        uint32_t bit_idx = static_cast<uint32_t>(bit_offset % 8);

        // Read up to 3 bytes to cover 10 bits starting at bit_idx
        uint32_t val = packed[byte_idx];
        val |= static_cast<uint32_t>(packed[byte_idx + 1]) << 8;
        if (bit_idx > 6) {
            val |= static_cast<uint32_t>(packed[byte_idx + 2]) << 16;
        }
        linear[i] = static_cast<uint16_t>((val >> bit_idx) & 0x3FF);
        bit_offset += 10;
    }

    // Transpose from [depth][frames] to [frames][depth]
    for (uint32_t d = 0; d < depth; ++d) {
        for (uint32_t f = 0; f < frames; ++f) {
            out_frame_major[static_cast<size_t>(f) * depth + d] =
                linear[static_cast<size_t>(d) * frames + f];
        }
    }
}

struct FileCloser {
    FILE* f;
    ~FileCloser() { if (f) std::fclose(f); }
};

}  // namespace

TokenStream read_sst(const std::string& path) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) throw std::runtime_error("Cannot open SST file: " + path);
    FileCloser closer{f};

    RawFileHeader hdr{};
    if (std::fread(&hdr, sizeof(hdr), 1, f) != 1) {
        throw std::runtime_error("Truncated SST1 header: " + path);
    }

    if (std::memcmp(hdr.magic, "SST1", 4) != 0) {
        throw std::runtime_error("Invalid magic in SST file: " + path);
    }
    if (hdr.version != kVersion) {
        throw std::runtime_error("Unsupported SST version: " + std::to_string(hdr.version));
    }
    if (hdr.header_size != kHeaderSize) {
        throw std::runtime_error("Invalid header size: " + std::to_string(hdr.header_size));
    }
    if (hdr.layout != kLayoutCodebookMajor) {
        throw std::runtime_error("Unsupported layout: " + std::to_string(hdr.layout));
    }
    if (hdr.max_rvq_depth > 64) {
        throw std::runtime_error("RVQ depth too large: " + std::to_string(hdr.max_rvq_depth));
    }
    if (hdr.bits_per_code != 10) {
        throw std::runtime_error("Unsupported bits_per_code: " + std::to_string(hdr.bits_per_code));
    }

    TokenStream result{};
    result.sample_rate = hdr.sample_rate;
    result.codec_frame_rate = hdr.frame_rate;
    result.frame_count = hdr.total_frame_count;
    result.rvq_depth = hdr.max_rvq_depth;
    result.original_samples = hdr.original_samples;
    result.tokens.resize(static_cast<size_t>(hdr.total_frame_count) * hdr.max_rvq_depth);

    uint32_t frames_read = 0;

    for (uint32_t chunk_idx = 0; chunk_idx < hdr.chunk_count; ++chunk_idx) {
        RawChunkHeader chdr{};
        if (std::fread(&chdr, sizeof(chdr), 1, f) != 1) {
            throw std::runtime_error("Truncated chunk header " + std::to_string(chunk_idx));
        }

        if (chdr.frames_in_chunk == 0 || chdr.frames_in_chunk > hdr.chunk_frames) {
            throw std::runtime_error("Invalid frame count in chunk " + std::to_string(chunk_idx));
        }
        if (chdr.stored_rvq_depth != hdr.max_rvq_depth) {
            throw std::runtime_error("RVQ depth mismatch in chunk " + std::to_string(chunk_idx));
        }

        uint32_t exp_bytes = expected_payload_bytes(
            chdr.frames_in_chunk, chdr.stored_rvq_depth, hdr.bits_per_code);
        if (chdr.payload_bytes != exp_bytes) {
            throw std::runtime_error("Payload size mismatch in chunk " + std::to_string(chunk_idx) +
                                     ": got " + std::to_string(chdr.payload_bytes) +
                                     ", expected " + std::to_string(exp_bytes));
        }

        // +2 extra bytes for safe 10-bit reading at the boundary
        std::vector<uint8_t> payload(chdr.payload_bytes + 2, 0);
        if (std::fread(payload.data(), 1, chdr.payload_bytes, f) != chdr.payload_bytes) {
            throw std::runtime_error("Truncated payload in chunk " + std::to_string(chunk_idx));
        }

        uint32_t actual_crc = crc32(payload.data(), chdr.payload_bytes);
        if (actual_crc != chdr.payload_crc32) {
            throw std::runtime_error("CRC mismatch in chunk " + std::to_string(chunk_idx) +
                                     ": computed " + std::to_string(actual_crc) +
                                     ", expected " + std::to_string(chdr.payload_crc32));
        }

        uint32_t total_values = chdr.frames_in_chunk * chdr.stored_rvq_depth;
        uint16_t* dest = result.tokens.data() +
                         static_cast<size_t>(frames_read) * hdr.max_rvq_depth;

        unpack_10bit_codebook_major(payload.data(), total_values,
                                    chdr.frames_in_chunk, chdr.stored_rvq_depth,
                                    dest);

        frames_read += chdr.frames_in_chunk;
    }

    if (frames_read != hdr.total_frame_count) {
        throw std::runtime_error("Frame count mismatch: read " + std::to_string(frames_read) +
                                 ", expected " + std::to_string(hdr.total_frame_count));
    }

    // Validate token range
    for (size_t i = 0; i < result.tokens.size(); ++i) {
        if (result.tokens[i] >= 1024) {
            throw std::runtime_error("Token out of range at index " + std::to_string(i) +
                                     ": " + std::to_string(result.tokens[i]));
        }
    }

    return result;
}

SstInspectResult inspect_sst(const std::string& path) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) throw std::runtime_error("Cannot open SST file: " + path);
    FileCloser closer{f};

    RawFileHeader hdr{};
    if (std::fread(&hdr, sizeof(hdr), 1, f) != 1) {
        throw std::runtime_error("Truncated SST1 header: " + path);
    }

    if (std::memcmp(hdr.magic, "SST1", 4) != 0) {
        throw std::runtime_error("Invalid magic: " + path);
    }

    SstInspectResult result{};
    result.header.sample_rate = hdr.sample_rate;
    result.header.channels = hdr.channels;
    result.header.frame_rate = hdr.frame_rate;
    result.header.max_rvq_depth = hdr.max_rvq_depth;
    result.header.bits_per_code = hdr.bits_per_code;
    result.header.chunk_frames = hdr.chunk_frames;
    result.header.total_frame_count = hdr.total_frame_count;
    result.header.original_samples = hdr.original_samples;
    result.header.chunk_count = hdr.chunk_count;
    result.header.layout = hdr.layout;
    result.all_crcs_valid = true;
    result.min_token = 1023;
    result.max_token = 0;
    result.total_payload_bytes = 0;
    result.duration_seconds = static_cast<double>(hdr.original_samples) /
                              hdr.sample_rate;

    for (uint32_t chunk_idx = 0; chunk_idx < hdr.chunk_count; ++chunk_idx) {
        RawChunkHeader chdr{};
        if (std::fread(&chdr, sizeof(chdr), 1, f) != 1) {
            throw std::runtime_error("Truncated chunk header " + std::to_string(chunk_idx));
        }

        std::vector<uint8_t> payload(chdr.payload_bytes + 2, 0);
        if (std::fread(payload.data(), 1, chdr.payload_bytes, f) != chdr.payload_bytes) {
            throw std::runtime_error("Truncated payload in chunk " + std::to_string(chunk_idx));
        }

        uint32_t actual_crc = crc32(payload.data(), chdr.payload_bytes);
        if (actual_crc != chdr.payload_crc32) {
            result.all_crcs_valid = false;
        }

        result.total_payload_bytes += chdr.payload_bytes;

        // Unpack to find min/max tokens
        uint32_t total_values = chdr.frames_in_chunk * chdr.stored_rvq_depth;
        uint64_t bit_offset = 0;
        for (uint32_t i = 0; i < total_values; ++i) {
            uint32_t byte_idx = static_cast<uint32_t>(bit_offset / 8);
            uint32_t bit_idx = static_cast<uint32_t>(bit_offset % 8);
            uint32_t val = payload[byte_idx];
            val |= static_cast<uint32_t>(payload[byte_idx + 1]) << 8;
            if (bit_idx > 6) {
                val |= static_cast<uint32_t>(payload[byte_idx + 2]) << 16;
            }
            uint16_t token = static_cast<uint16_t>((val >> bit_idx) & 0x3FF);
            if (token < result.min_token) result.min_token = token;
            if (token > result.max_token) result.max_token = token;
            bit_offset += 10;
        }
    }

    return result;
}

}  // namespace spectrostream
