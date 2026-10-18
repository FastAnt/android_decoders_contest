#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
#define SS_EXPORT __declspec(dllexport)
#else
#define SS_EXPORT __attribute__((visibility("default")))
#endif

typedef void* SpectroStreamDecoderHandle;
typedef void* SpectroStreamDecoderStreamHandle;

typedef struct SpectroStreamStreamInfo {
    int sample_rate;
    int channels;
    int total_blocks;
    int64_t total_pcm_frames;
    int block_pcm_frames;
} SpectroStreamStreamInfo;

SS_EXPORT SpectroStreamDecoderHandle spectrostream_decoder_create(
    const char* model_path,
    const char* codebooks_path,
    const char* window_path,
    int num_threads);

SS_EXPORT SpectroStreamDecoderHandle spectrostream_decoder_create_ex(
    const char* model_path,
    const char* codebooks_path,
    const char* window_path,
    int num_threads,
    int num_cores);

SS_EXPORT int spectrostream_decoder_decode_file(
    SpectroStreamDecoderHandle handle,
    const char* sst_path,
    float** pcm_out,
    int64_t* frame_count_out,
    int* sample_rate_out,
    int* channels_out);

SS_EXPORT void spectrostream_decoder_free_pcm(float* pcm);

SS_EXPORT SpectroStreamDecoderStreamHandle spectrostream_decoder_stream_create(
    SpectroStreamDecoderHandle handle,
    const char* sst_path);

SS_EXPORT int spectrostream_decoder_stream_decode_next(
    SpectroStreamDecoderStreamHandle stream_handle,
    float** pcm_out,
    int64_t* frame_count_out,
    int* sample_rate_out,
    int* channels_out,
    int* blocks_remaining_out,
    int* done_out);

SS_EXPORT int spectrostream_decoder_stream_decode_next_ex(
    SpectroStreamDecoderStreamHandle stream_handle,
    float** pcm_out,
    int64_t* frame_count_out,
    int* sample_rate_out,
    int* channels_out,
    int* blocks_remaining_out,
    int* done_out,
    int* current_block_index_out,
    int* total_blocks_out,
    int* canceled_out);

SS_EXPORT int spectrostream_decoder_stream_get_info(
    SpectroStreamDecoderStreamHandle stream_handle,
    SpectroStreamStreamInfo* info_out);

SS_EXPORT int spectrostream_decoder_stream_cancel(
    SpectroStreamDecoderStreamHandle stream_handle);

SS_EXPORT const char* spectrostream_decoder_stream_last_error(
    SpectroStreamDecoderStreamHandle stream_handle);

SS_EXPORT void spectrostream_decoder_stream_destroy(
    SpectroStreamDecoderStreamHandle stream_handle);

SS_EXPORT void spectrostream_decoder_destroy(SpectroStreamDecoderHandle handle);

SS_EXPORT const char* spectrostream_decoder_last_error(
    SpectroStreamDecoderHandle handle);

#ifdef __cplusplus
}
#endif
