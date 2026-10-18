#include "spectrostream/decoder_c_api.h"
#include "spectrostream/decoder.h"

#include <cstdlib>
#include <cstring>
#include <new>
#include <string>

struct DecoderHandle {
    spectrostream::Decoder* decoder;
    std::string last_error;
};

struct DecoderStreamHandle {
    DecoderHandle* owner;
    spectrostream::Decoder::StreamSession* session;
    std::string last_error;
};

extern "C" {

SS_EXPORT SpectroStreamDecoderHandle spectrostream_decoder_create(
    const char* model_path,
    const char* codebooks_path,
    const char* window_path,
    int num_threads) {

    auto* handle = new (std::nothrow) DecoderHandle{};
    if (!handle) return nullptr;

    try {
        spectrostream::DecoderConfig config;
        config.model_path = model_path;
        config.codebooks_path = codebooks_path;
        config.window_path = window_path;
        config.num_threads = num_threads > 0 ? num_threads : 4;
        config.use_xnnpack = true;

        handle->decoder = new spectrostream::Decoder(config);
        return static_cast<SpectroStreamDecoderHandle>(handle);
    } catch (const std::exception& e) {
        handle->last_error = e.what();
        handle->decoder = nullptr;
        return static_cast<SpectroStreamDecoderHandle>(handle);
    }
}

SS_EXPORT int spectrostream_decoder_decode_file(
    SpectroStreamDecoderHandle h,
    const char* sst_path,
    float** pcm_out,
    int64_t* frame_count_out,
    int* sample_rate_out,
    int* channels_out) {

    auto* handle = static_cast<DecoderHandle*>(h);
    if (!handle || !handle->decoder) {
        if (handle) handle->last_error = "Decoder not initialized";
        return -1;
    }
    if (!sst_path || !pcm_out || !frame_count_out || !sample_rate_out || !channels_out) {
        handle->last_error = "Invalid decode_file arguments";
        return -1;
    }

    try {
        auto result = handle->decoder->decode_file(sst_path);

        // Allocate output buffer for caller
        size_t bytes = result.pcm.size() * sizeof(float);
        float* out = static_cast<float*>(std::malloc(bytes));
        if (!out) {
            handle->last_error = "Failed to allocate output buffer";
            return -1;
        }
        std::memcpy(out, result.pcm.data(), bytes);

        *pcm_out = out;
        *frame_count_out = result.frame_count;
        *sample_rate_out = result.sample_rate;
        *channels_out = result.channels;
        return 0;
    } catch (const std::exception& e) {
        handle->last_error = e.what();
        return -1;
    }
}

SS_EXPORT void spectrostream_decoder_free_pcm(float* pcm) {
    std::free(pcm);
}

SS_EXPORT SpectroStreamDecoderStreamHandle spectrostream_decoder_stream_create(
    SpectroStreamDecoderHandle h,
    const char* sst_path) {

    auto* handle = static_cast<DecoderHandle*>(h);
    if (!handle || !handle->decoder) {
        if (handle) handle->last_error = "Decoder not initialized";
        return nullptr;
    }
    if (!sst_path) {
        handle->last_error = "Invalid stream_create arguments";
        return nullptr;
    }

    auto* stream = new (std::nothrow) DecoderStreamHandle{};
    if (!stream) {
        handle->last_error = "Failed to allocate stream handle";
        return nullptr;
    }

    stream->owner = handle;
    stream->session = nullptr;
    try {
        stream->session = handle->decoder->create_stream_session_raw(sst_path);
        return static_cast<SpectroStreamDecoderStreamHandle>(stream);
    } catch (const std::exception& e) {
        stream->last_error = e.what();
        handle->last_error = e.what();
        delete stream;
        return nullptr;
    }
}

SS_EXPORT int spectrostream_decoder_stream_decode_next(
    SpectroStreamDecoderStreamHandle sh,
    float** pcm_out,
    int64_t* frame_count_out,
    int* sample_rate_out,
    int* channels_out,
    int* blocks_remaining_out,
    int* done_out) {

    return spectrostream_decoder_stream_decode_next_ex(
        sh,
        pcm_out,
        frame_count_out,
        sample_rate_out,
        channels_out,
        blocks_remaining_out,
        done_out,
        nullptr,
        nullptr,
        nullptr);
}

SS_EXPORT int spectrostream_decoder_stream_decode_next_ex(
    SpectroStreamDecoderStreamHandle sh,
    float** pcm_out,
    int64_t* frame_count_out,
    int* sample_rate_out,
    int* channels_out,
    int* blocks_remaining_out,
    int* done_out,
    int* current_block_index_out,
    int* total_blocks_out,
    int* canceled_out) {

    auto* stream = static_cast<DecoderStreamHandle*>(sh);
    if (!stream || !stream->owner || !stream->owner->decoder || !stream->session) {
        if (stream && stream->owner) stream->owner->last_error = "Stream not initialized";
        return -1;
    }
    if (!pcm_out || !frame_count_out || !sample_rate_out || !channels_out ||
        !blocks_remaining_out || !done_out) {
        stream->last_error = "Invalid stream_decode_next arguments";
        stream->owner->last_error = stream->last_error;
        return -1;
    }

    try {
        auto result = stream->owner->decoder->decode_next_block(*stream->session);

        *pcm_out = nullptr;
        *frame_count_out = result.frame_count;
        *sample_rate_out = result.sample_rate;
        *channels_out = result.channels;
        *blocks_remaining_out = static_cast<int>(result.blocks_remaining);
        *done_out = result.done ? 1 : 0;
        if (current_block_index_out) {
            *current_block_index_out = static_cast<int>(result.current_block_index);
        }
        if (total_blocks_out) {
            *total_blocks_out = static_cast<int>(result.total_blocks);
        }
        if (canceled_out) {
            *canceled_out = result.canceled ? 1 : 0;
        }

        if (!result.pcm.empty()) {
            size_t bytes = result.pcm.size() * sizeof(float);
            float* out = static_cast<float*>(std::malloc(bytes));
            if (!out) {
                stream->last_error = "Failed to allocate stream output buffer";
                stream->owner->last_error = stream->last_error;
                return -1;
            }
            std::memcpy(out, result.pcm.data(), bytes);
            *pcm_out = out;
        }

        stream->last_error.clear();

        return 0;
    } catch (const std::exception& e) {
        stream->last_error = e.what();
        stream->owner->last_error = e.what();
        return -1;
    }
}

SS_EXPORT int spectrostream_decoder_stream_get_info(
    SpectroStreamDecoderStreamHandle sh,
    SpectroStreamStreamInfo* info_out) {

    auto* stream = static_cast<DecoderStreamHandle*>(sh);
    if (!stream || !stream->owner || !stream->owner->decoder || !stream->session) {
        if (stream && stream->owner) stream->owner->last_error = "Stream not initialized";
        return -1;
    }
    if (!info_out) {
        stream->last_error = "Invalid stream_get_info arguments";
        stream->owner->last_error = stream->last_error;
        return -1;
    }

    try {
        const auto info = stream->owner->decoder->get_stream_info(*stream->session);
        info_out->sample_rate = info.sample_rate;
        info_out->channels = info.channels;
        info_out->total_blocks = static_cast<int>(info.total_blocks);
        info_out->total_pcm_frames = info.total_pcm_frames;
        info_out->block_pcm_frames = info.block_pcm_frames;
        stream->last_error.clear();
        return 0;
    } catch (const std::exception& e) {
        stream->last_error = e.what();
        stream->owner->last_error = e.what();
        return -1;
    }
}

SS_EXPORT int spectrostream_decoder_stream_cancel(
    SpectroStreamDecoderStreamHandle sh) {

    auto* stream = static_cast<DecoderStreamHandle*>(sh);
    if (!stream || !stream->owner || !stream->owner->decoder || !stream->session) {
        if (stream && stream->owner) stream->owner->last_error = "Stream not initialized";
        return -1;
    }

    try {
        stream->owner->decoder->cancel_stream_session(*stream->session);
        stream->last_error.clear();
        return 0;
    } catch (const std::exception& e) {
        stream->last_error = e.what();
        stream->owner->last_error = e.what();
        return -1;
    }
}

SS_EXPORT const char* spectrostream_decoder_stream_last_error(
    SpectroStreamDecoderStreamHandle sh) {
    auto* stream = static_cast<DecoderStreamHandle*>(sh);
    if (!stream) return "null stream handle";
    return stream->last_error.c_str();
}

SS_EXPORT void spectrostream_decoder_stream_destroy(
    SpectroStreamDecoderStreamHandle sh) {
    auto* stream = static_cast<DecoderStreamHandle*>(sh);
    if (stream && stream->owner && stream->owner->decoder && stream->session) {
        stream->owner->decoder->destroy_stream_session(stream->session);
        stream->session = nullptr;
    }
    delete stream;
}

SS_EXPORT void spectrostream_decoder_destroy(SpectroStreamDecoderHandle h) {
    auto* handle = static_cast<DecoderHandle*>(h);
    if (handle) {
        delete handle->decoder;
        delete handle;
    }
}

SS_EXPORT const char* spectrostream_decoder_last_error(SpectroStreamDecoderHandle h) {
    auto* handle = static_cast<DecoderHandle*>(h);
    if (!handle) return "null handle";
    return handle->last_error.c_str();
}

}  // extern "C"
