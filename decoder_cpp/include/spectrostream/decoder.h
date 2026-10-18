#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace spectrostream {

struct DecoderConfig {
    std::string model_path;
    std::string codebooks_path;
    std::string window_path;
    int num_threads = 4;
    int num_cores = 0;
    bool use_xnnpack = true;
    bool use_gpu = false;
};

struct DecodeResult {
    std::vector<float> pcm;  // interleaved stereo float32
    int32_t sample_rate;
    int32_t channels;
    int64_t frame_count;  // PCM frames (samples per channel)

    double model_load_ms;
    double codebook_load_ms;
    double sst_parse_ms;
    double rvq_ms;
    double inference_ms;
    double istft_ms;
    double total_ms;
    double audio_duration_s;
    double rtf;
};

struct StreamDecodeResult {
    std::vector<float> pcm;  // interleaved stereo float32
    int32_t sample_rate;
    int32_t channels;
    int64_t frame_count;      // PCM frames (samples per channel)
    uint32_t blocks_remaining;
    uint32_t current_block_index;
    uint32_t total_blocks;
    bool canceled;
    bool done;
};

struct StreamInfo {
    int32_t sample_rate;
    int32_t channels;
    uint32_t total_blocks;
    int64_t total_pcm_frames;
    int32_t block_pcm_frames;
};

class Decoder {
public:
    struct StreamSession;

    explicit Decoder(const DecoderConfig& config);
    ~Decoder();

    Decoder(const Decoder&) = delete;
    Decoder& operator=(const Decoder&) = delete;
    Decoder(Decoder&&) noexcept;
    Decoder& operator=(Decoder&&) noexcept;

    DecodeResult decode_file(const std::string& sst_path);
    std::unique_ptr<StreamSession> create_stream_session(const std::string& sst_path) const;
    StreamSession* create_stream_session_raw(const std::string& sst_path) const;
    StreamDecodeResult decode_next_block(StreamSession& session);
    StreamDecodeResult decode_next_block_ex(StreamSession& session);
    StreamInfo get_stream_info(const StreamSession& session) const;
    void cancel_stream_session(StreamSession& session) const;
    const char* stream_last_error(const StreamSession& session) const;
    void destroy_stream_session(StreamSession* session) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace spectrostream
