#include "spectrostream/decoder.h"
#include "spectrostream/istft.h"
#include "spectrostream/litert_runner.h"
#include "spectrostream/rvq_dequantizer.h"
#include "spectrostream/sst_reader.h"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <stdexcept>

namespace spectrostream {

struct Decoder::Impl {
    RvqDequantizer dequantizer;
    LiteRtRunner runner;
    Istft istft;

    Impl(const DecoderConfig& config)
        : dequantizer(config.codebooks_path),
          runner(config.model_path, LiteRtConfig{config.num_threads, config.num_cores, config.use_xnnpack, config.use_gpu}),
          istft(config.window_path) {}
};

struct Decoder::StreamSession {
    TokenStream tokens;
    uint32_t next_block = 0;
    uint32_t num_core_blocks = 0;
    int model_frames = 0;
    int stft_frames_out = 0;
    int core_frames = 25;
    int context_frames = 0;
    int samples_per_codec_frame = 0;
    int core_pcm_offset = 0;
    int block_pcm_frames = 0;
    int64_t target_pcm_frames = 0;
    int64_t emitted_pcm_frames = 0;
    bool cancel_requested = false;
    bool canceled = false;
    std::string last_error;
    std::vector<float> model_embeddings;
};

namespace {
using Clock = std::chrono::high_resolution_clock;
double ms_since(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

struct DecoderLayout {
    int model_frames;
    int stft_frames_out;
    int core_frames;
    int context_frames;
    int samples_per_codec_frame;
    int core_pcm_offset;
    uint32_t num_core_blocks;
};

struct BlockSynthesisResult {
    std::vector<float> pcm;
    uint32_t actual_core_frames;
};

DecoderLayout build_layout(const LiteRtRunner& runner, const TokenStream& tokens) {
    DecoderLayout layout{};
    layout.model_frames = runner.input_frames();
    layout.stft_frames_out = runner.output_stft_frames();
    layout.core_frames = 25;

    if (layout.model_frames <= 0 || layout.stft_frames_out <= 0) {
        throw std::runtime_error("Invalid model IO shape");
    }
    if (layout.model_frames < layout.core_frames) {
        throw std::runtime_error("Model frames smaller than core frame size");
    }
    if (tokens.codec_frame_rate == 0) {
        throw std::runtime_error("SST codec frame rate is zero");
    }

    layout.context_frames = (layout.model_frames - layout.core_frames) / 2;
    if (layout.context_frames < 0) {
        layout.context_frames = 0;
    }

    layout.samples_per_codec_frame = Istft::kSampleRate / static_cast<int>(tokens.codec_frame_rate);
    if (layout.samples_per_codec_frame <= 0) {
        throw std::runtime_error("Invalid samples-per-codec-frame ratio");
    }

    layout.core_pcm_offset = layout.context_frames * layout.samples_per_codec_frame;
    layout.num_core_blocks =
        (tokens.frame_count + static_cast<uint32_t>(layout.core_frames) - 1) /
        static_cast<uint32_t>(layout.core_frames);
    return layout;
}

BlockSynthesisResult decode_core_block(
    const RvqDequantizer& dequantizer,
    LiteRtRunner& runner,
    const Istft& istft,
    const TokenStream& tokens,
    const DecoderLayout& layout,
    uint32_t block_index,
    std::vector<float>& model_embeddings,
    double* rvq_ms,
    double* inference_ms,
    double* istft_ms) {

    if (block_index >= layout.num_core_blocks) {
        return BlockSynthesisResult{};
    }

    const uint32_t total_frames = tokens.frame_count;
    const uint32_t core_start = block_index * static_cast<uint32_t>(layout.core_frames);
    const uint32_t core_end =
        std::min(core_start + static_cast<uint32_t>(layout.core_frames), total_frames);
    const uint32_t actual_core = core_end - core_start;

    int32_t read_start = static_cast<int32_t>(core_start) - layout.context_frames;
    int32_t read_end = static_cast<int32_t>(core_end) + layout.context_frames;

    const int32_t valid_start = std::max(read_start, 0);
    const int32_t valid_end = std::min(read_end, static_cast<int32_t>(total_frames));
    const uint32_t valid_frames = static_cast<uint32_t>(valid_end - valid_start);

    auto t0 = Clock::now();
    const uint16_t* block_tokens = tokens.tokens.data() +
                                   static_cast<size_t>(valid_start) * tokens.rvq_depth;
    auto embeddings = dequantizer.dequantize(block_tokens, valid_frames, tokens.rvq_depth);

    std::fill(model_embeddings.begin(), model_embeddings.end(), 0.0f);
    const int pad_left_frames = valid_start - read_start;
    std::memcpy(
        model_embeddings.data() +
            static_cast<size_t>(pad_left_frames) * RvqDequantizer::kEmbeddingDim,
        embeddings.data(),
        embeddings.size() * sizeof(float));
    if (rvq_ms) {
        *rvq_ms += ms_since(t0);
    }

    t0 = Clock::now();
    const float* spectrum = runner.invoke(model_embeddings.data());
    if (inference_ms) {
        *inference_ms += ms_since(t0);
    }

    t0 = Clock::now();
    const int istft_target = layout.model_frames * layout.samples_per_codec_frame;
    auto full_pcm = istft.synthesize(spectrum, layout.stft_frames_out, istft_target);
    if (istft_ms) {
        *istft_ms += ms_since(t0);
    }

    int samples_to_take =
        static_cast<int>(actual_core) * layout.samples_per_codec_frame;
    int interleaved_offset = layout.core_pcm_offset * Istft::kChannels;
    int interleaved_count = samples_to_take * Istft::kChannels;

    if (interleaved_offset >= static_cast<int>(full_pcm.size()) || interleaved_count <= 0) {
        return BlockSynthesisResult{{}, actual_core};
    }

    interleaved_count = std::min(
        interleaved_count,
        static_cast<int>(full_pcm.size()) - interleaved_offset);

    BlockSynthesisResult result{};
    result.actual_core_frames = actual_core;
    result.pcm.insert(
        result.pcm.end(),
        full_pcm.begin() + interleaved_offset,
        full_pcm.begin() + interleaved_offset + interleaved_count);
    return result;
}
}  // namespace

Decoder::Decoder(const DecoderConfig& config) : impl_(std::make_unique<Impl>(config)) {}
Decoder::~Decoder() = default;
Decoder::Decoder(Decoder&&) noexcept = default;
Decoder& Decoder::operator=(Decoder&&) noexcept = default;

DecodeResult Decoder::decode_file(const std::string& sst_path) {
    DecodeResult result{};
    auto total_start = Clock::now();

    // Parse SST
    auto t0 = Clock::now();
    TokenStream tokens = read_sst(sst_path);
    result.sst_parse_ms = ms_since(t0);

    const DecoderLayout layout = build_layout(impl_->runner, tokens);

    result.sample_rate = tokens.sample_rate;
    result.channels = 2;

    // Target output size from SST header
    const int64_t target_pcm_frames = static_cast<int64_t>(tokens.original_samples);
    const int64_t target_interleaved = target_pcm_frames * result.channels;

    const uint32_t num_core_blocks = layout.num_core_blocks;

    result.pcm.reserve(target_interleaved);

    double rvq_ms_total = 0.0;
    double inference_ms_total = 0.0;
    double istft_ms_total = 0.0;

    // Scratch buffer for padded embeddings
    std::vector<float> model_embeddings(
        static_cast<size_t>(layout.model_frames) * RvqDequantizer::kEmbeddingDim, 0.0f);

    for (uint32_t block = 0; block < num_core_blocks; ++block) {
        BlockSynthesisResult block_result = decode_core_block(
            impl_->dequantizer,
            impl_->runner,
            impl_->istft,
            tokens,
            layout,
            block,
            model_embeddings,
            &rvq_ms_total,
            &inference_ms_total,
            &istft_ms_total);
        result.pcm.insert(
            result.pcm.end(),
            block_result.pcm.begin(),
            block_result.pcm.end());
    }

    // Trim to original sample count
    if (static_cast<int64_t>(result.pcm.size()) > target_interleaved) {
        result.pcm.resize(target_interleaved);
    }

    result.frame_count = static_cast<int64_t>(result.pcm.size()) / result.channels;
    result.rvq_ms = rvq_ms_total;
    result.inference_ms = inference_ms_total;
    result.istft_ms = istft_ms_total;
    result.total_ms = ms_since(total_start);
    result.audio_duration_s = static_cast<double>(result.frame_count) / result.sample_rate;
    result.rtf = (result.total_ms / 1000.0) / result.audio_duration_s;

    return result;
}

std::unique_ptr<Decoder::StreamSession> Decoder::create_stream_session(
    const std::string& sst_path) const {
    auto session = std::make_unique<StreamSession>();
    session->tokens = read_sst(sst_path);

    const DecoderLayout layout = build_layout(impl_->runner, session->tokens);
    session->model_frames = layout.model_frames;
    session->stft_frames_out = layout.stft_frames_out;
    session->core_frames = layout.core_frames;
    session->context_frames = layout.context_frames;
    session->samples_per_codec_frame = layout.samples_per_codec_frame;
    session->core_pcm_offset = layout.core_pcm_offset;
    session->block_pcm_frames =
        session->core_frames * session->samples_per_codec_frame;
    session->num_core_blocks = layout.num_core_blocks;
    session->target_pcm_frames = static_cast<int64_t>(session->tokens.original_samples);
    session->model_embeddings.assign(
        static_cast<size_t>(session->model_frames) * RvqDequantizer::kEmbeddingDim,
        0.0f);
    return session;
}

Decoder::StreamSession* Decoder::create_stream_session_raw(
    const std::string& sst_path) const {
    return create_stream_session(sst_path).release();
}

StreamDecodeResult Decoder::decode_next_block(StreamSession& session) {
    StreamDecodeResult result = decode_next_block_ex(session);
    return result;
}

StreamDecodeResult Decoder::decode_next_block_ex(StreamSession& session) {
    StreamDecodeResult result{};
    result.current_block_index = session.next_block;
    result.total_blocks = session.num_core_blocks;
    result.canceled = false;
    result.sample_rate = static_cast<int32_t>(session.tokens.sample_rate);
    result.channels = 2;

    if (session.cancel_requested || session.canceled) {
        session.canceled = true;
        result.frame_count = 0;
        result.blocks_remaining = 0;
        result.current_block_index = session.next_block;
        result.total_blocks = session.num_core_blocks;
        result.canceled = true;
        result.done = true;
        return result;
    }

    if (session.next_block >= session.num_core_blocks ||
        session.emitted_pcm_frames >= session.target_pcm_frames) {
        result.frame_count = 0;
        result.blocks_remaining = 0;
        result.current_block_index = session.next_block;
        result.total_blocks = session.num_core_blocks;
        result.done = true;
        return result;
    }

    DecoderLayout layout{};
    layout.model_frames = session.model_frames;
    layout.stft_frames_out = session.stft_frames_out;
    layout.core_frames = session.core_frames;
    layout.context_frames = session.context_frames;
    layout.samples_per_codec_frame = session.samples_per_codec_frame;
    layout.core_pcm_offset = session.core_pcm_offset;
    layout.num_core_blocks = session.num_core_blocks;

    BlockSynthesisResult block_result;
    try {
        block_result = decode_core_block(
            impl_->dequantizer,
            impl_->runner,
            impl_->istft,
            session.tokens,
            layout,
            session.next_block,
            session.model_embeddings,
            nullptr,
            nullptr,
            nullptr);
    } catch (const std::exception& e) {
        session.last_error = e.what();
        throw;
    }

    result.current_block_index = session.next_block;
    ++session.next_block;

    int64_t block_frames = static_cast<int64_t>(block_result.pcm.size()) / result.channels;
    if (session.emitted_pcm_frames + block_frames > session.target_pcm_frames) {
        const int64_t allowed_frames = std::max<int64_t>(
            0, session.target_pcm_frames - session.emitted_pcm_frames);
        block_result.pcm.resize(static_cast<size_t>(allowed_frames * result.channels));
        block_frames = allowed_frames;
    }

    session.emitted_pcm_frames += block_frames;
    result.pcm = std::move(block_result.pcm);
    result.frame_count = block_frames;
    result.blocks_remaining = session.num_core_blocks - session.next_block;
    result.total_blocks = session.num_core_blocks;
    result.canceled = false;
    result.done =
        (result.blocks_remaining == 0) || (session.emitted_pcm_frames >= session.target_pcm_frames);
    return result;
}

StreamInfo Decoder::get_stream_info(const StreamSession& session) const {
    StreamInfo info{};
    info.sample_rate = static_cast<int32_t>(session.tokens.sample_rate);
    info.channels = 2;
    info.total_blocks = session.num_core_blocks;
    info.total_pcm_frames = session.target_pcm_frames;
    info.block_pcm_frames = session.block_pcm_frames;
    return info;
}

void Decoder::cancel_stream_session(StreamSession& session) const {
    session.cancel_requested = true;
    session.canceled = true;
    session.last_error.clear();
}

const char* Decoder::stream_last_error(const StreamSession& session) const {
    return session.last_error.c_str();
}

void Decoder::destroy_stream_session(StreamSession* session) const {
    delete session;
}

}  // namespace spectrostream
