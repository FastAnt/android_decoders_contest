#include "spectrostream/decoder_c_api.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int test_create_destroy(const char* model, const char* codebooks, const char* window) {
    printf("TEST: create/destroy... ");

    SpectroStreamDecoderHandle h = spectrostream_decoder_create(model, codebooks, window, 4);
    if (!h) {
        printf("FAIL (null handle)\n");
        return 1;
    }

    const char* err = spectrostream_decoder_last_error(h);
    if (err && strlen(err) > 0) {
        printf("FAIL (error on create: %s)\n", err);
        spectrostream_decoder_destroy(h);
        return 1;
    }

    spectrostream_decoder_destroy(h);
    printf("OK\n");
    return 0;
}

static int test_decode(const char* model, const char* codebooks, const char* window,
                       const char* sst_path) {
    printf("TEST: decode file... ");

    SpectroStreamDecoderHandle h = spectrostream_decoder_create(model, codebooks, window, 4);
    if (!h) {
        printf("FAIL (null handle)\n");
        return 1;
    }

    float* pcm = NULL;
    int64_t frame_count = 0;
    int sample_rate = 0;
    int channels = 0;

    int rc = spectrostream_decoder_decode_file(h, sst_path, &pcm, &frame_count,
                                               &sample_rate, &channels);
    if (rc != 0) {
        printf("FAIL (rc=%d, error: %s)\n", rc, spectrostream_decoder_last_error(h));
        spectrostream_decoder_destroy(h);
        return 1;
    }

    if (!pcm || frame_count <= 0 || sample_rate != 48000 || channels != 2) {
        printf("FAIL (invalid output: frames=%lld sr=%d ch=%d pcm=%p)\n",
               (long long)frame_count, sample_rate, channels, (void*)pcm);
        if (pcm) spectrostream_decoder_free_pcm(pcm);
        spectrostream_decoder_destroy(h);
        return 1;
    }

    printf("OK (frames=%lld, sr=%d, ch=%d)\n", (long long)frame_count, sample_rate, channels);

    spectrostream_decoder_free_pcm(pcm);
    spectrostream_decoder_destroy(h);
    return 0;
}

static int test_double_decode(const char* model, const char* codebooks, const char* window,
                              const char* sst_path) {
    printf("TEST: double decode (reuse handle)... ");

    SpectroStreamDecoderHandle h = spectrostream_decoder_create(model, codebooks, window, 4);
    if (!h) {
        printf("FAIL (null handle)\n");
        return 1;
    }

    float* pcm1 = NULL;
    int64_t frames1 = 0;
    int sr1 = 0, ch1 = 0;

    int rc = spectrostream_decoder_decode_file(h, sst_path, &pcm1, &frames1, &sr1, &ch1);
    if (rc != 0) {
        printf("FAIL (first decode: %s)\n", spectrostream_decoder_last_error(h));
        spectrostream_decoder_destroy(h);
        return 1;
    }
    spectrostream_decoder_free_pcm(pcm1);

    float* pcm2 = NULL;
    int64_t frames2 = 0;
    int sr2 = 0, ch2 = 0;

    rc = spectrostream_decoder_decode_file(h, sst_path, &pcm2, &frames2, &sr2, &ch2);
    if (rc != 0) {
        printf("FAIL (second decode: %s)\n", spectrostream_decoder_last_error(h));
        spectrostream_decoder_destroy(h);
        return 1;
    }

    if (frames1 != frames2) {
        printf("FAIL (frame count mismatch: %lld vs %lld)\n",
               (long long)frames1, (long long)frames2);
        spectrostream_decoder_free_pcm(pcm2);
        spectrostream_decoder_destroy(h);
        return 1;
    }

    spectrostream_decoder_free_pcm(pcm2);
    spectrostream_decoder_destroy(h);
    printf("OK (both decodes: %lld frames)\n", (long long)frames1);
    return 0;
}

static int test_stream_decode(const char* model, const char* codebooks, const char* window,
                              const char* sst_path) {
    printf("TEST: stream decode + info/cancel... ");

    SpectroStreamDecoderHandle h = spectrostream_decoder_create(model, codebooks, window, 4);
    if (!h) {
        printf("FAIL (null handle)\n");
        return 1;
    }

    SpectroStreamDecoderStreamHandle stream =
        spectrostream_decoder_stream_create(h, sst_path);
    if (!stream) {
        printf("FAIL (stream create failed: %s)\n", spectrostream_decoder_last_error(h));
        spectrostream_decoder_destroy(h);
        return 1;
    }

    SpectroStreamStreamInfo info;
    if (spectrostream_decoder_stream_get_info(stream, &info) != 0) {
        printf("FAIL (stream_get_info failed: %s)\n",
               spectrostream_decoder_stream_last_error(stream));
        spectrostream_decoder_stream_destroy(stream);
        spectrostream_decoder_destroy(h);
        return 1;
    }

    if (info.sample_rate != 48000 || info.channels != 2 ||
        info.total_blocks <= 0 || info.total_pcm_frames <= 0 || info.block_pcm_frames <= 0) {
        printf("FAIL (invalid stream info: sr=%d ch=%d total_blocks=%d total_frames=%lld block_frames=%d)\n",
               info.sample_rate,
               info.channels,
               info.total_blocks,
               (long long)info.total_pcm_frames,
               info.block_pcm_frames);
        spectrostream_decoder_stream_destroy(stream);
        spectrostream_decoder_destroy(h);
        return 1;
    }

    int total_calls = 0;
    int done = 0;
    int64_t total_frames = 0;
    int canceled = 0;

    while (!done && total_calls < 2) {
        float* pcm = NULL;
        int64_t frame_count = 0;
        int sample_rate = 0;
        int channels = 0;
        int blocks_remaining = 0;
        int current_block_index = 0;
        int total_blocks = 0;

        int rc = spectrostream_decoder_stream_decode_next_ex(
            stream,
            &pcm,
            &frame_count,
            &sample_rate,
            &channels,
            &blocks_remaining,
            &done,
            &current_block_index,
            &total_blocks,
            &canceled);
        if (rc != 0) {
            printf("FAIL (stream decode failed: %s)\n", spectrostream_decoder_last_error(h));
            spectrostream_decoder_stream_destroy(stream);
            spectrostream_decoder_destroy(h);
            return 1;
        }

        if (sample_rate != 48000 || channels != 2 || frame_count <= 0 || !pcm) {
            printf("FAIL (invalid stream output: frames=%lld sr=%d ch=%d pcm=%p)\n",
                   (long long)frame_count, sample_rate, channels, (void*)pcm);
            if (pcm) spectrostream_decoder_free_pcm(pcm);
            spectrostream_decoder_stream_destroy(stream);
            spectrostream_decoder_destroy(h);
            return 1;
        }

        if (current_block_index < 0 || total_blocks <= 0 ||
            current_block_index >= total_blocks) {
            printf("FAIL (invalid progress: idx=%d total=%d)\n",
                   current_block_index,
                   total_blocks);
            spectrostream_decoder_free_pcm(pcm);
            spectrostream_decoder_stream_destroy(stream);
            spectrostream_decoder_destroy(h);
            return 1;
        }

        total_frames += frame_count;
        ++total_calls;
        spectrostream_decoder_free_pcm(pcm);
    }

    if (spectrostream_decoder_stream_cancel(stream) != 0) {
        printf("FAIL (stream cancel failed: %s)\n",
               spectrostream_decoder_stream_last_error(stream));
        spectrostream_decoder_stream_destroy(stream);
        spectrostream_decoder_destroy(h);
        return 1;
    }

    {
        float* pcm = NULL;
        int64_t frame_count = 0;
        int sample_rate = 0;
        int channels = 0;
        int blocks_remaining = 0;
        int current_block_index = 0;
        int total_blocks = 0;

        int rc = spectrostream_decoder_stream_decode_next_ex(
            stream,
            &pcm,
            &frame_count,
            &sample_rate,
            &channels,
            &blocks_remaining,
            &done,
            &current_block_index,
            &total_blocks,
            &canceled);

        if (rc != 0) {
            printf("FAIL (stream decode after cancel failed: %s)\n",
                   spectrostream_decoder_stream_last_error(stream));
            spectrostream_decoder_stream_destroy(stream);
            spectrostream_decoder_destroy(h);
            return 1;
        }

        if (!done || !canceled || frame_count != 0 || pcm != NULL) {
            printf("FAIL (cancel state invalid: done=%d canceled=%d frames=%lld pcm=%p)\n",
                   done, canceled, (long long)frame_count, (void*)pcm);
            if (pcm) spectrostream_decoder_free_pcm(pcm);
            spectrostream_decoder_stream_destroy(stream);
            spectrostream_decoder_destroy(h);
            return 1;
        }
    }

    {
        int rc = spectrostream_decoder_stream_get_info(stream, NULL);
        if (rc == 0) {
            printf("FAIL (stream_get_info(NULL) unexpectedly succeeded)\n");
            spectrostream_decoder_stream_destroy(stream);
            spectrostream_decoder_destroy(h);
            return 1;
        }
        const char* stream_err = spectrostream_decoder_stream_last_error(stream);
        if (!stream_err || strlen(stream_err) == 0) {
            printf("FAIL (missing stream_last_error after invalid call)\n");
            spectrostream_decoder_stream_destroy(stream);
            spectrostream_decoder_destroy(h);
            return 1;
        }
    }

    if (total_calls == 0 || total_frames <= 0) {
        printf("FAIL (no stream data produced)\n");
        spectrostream_decoder_stream_destroy(stream);
        spectrostream_decoder_destroy(h);
        return 1;
    }

    spectrostream_decoder_stream_destroy(stream);
    spectrostream_decoder_destroy(h);
    printf("OK (%d calls, %lld frames)\n", total_calls, (long long)total_frames);
    return 0;
}

static int test_error_handling(void) {
    printf("TEST: error handling... ");

    SpectroStreamDecoderHandle h = spectrostream_decoder_create(
        "/nonexistent/model.tflite",
        "/nonexistent/codebooks.f32",
        "/nonexistent/window.f32", 4);

    if (!h) {
        printf("FAIL (null handle on error - should still return handle)\n");
        return 1;
    }

    const char* err = spectrostream_decoder_last_error(h);
    if (!err || strlen(err) == 0) {
        printf("FAIL (no error message for invalid paths)\n");
        spectrostream_decoder_destroy(h);
        return 1;
    }

    printf("OK (got error: %.60s...)\n", err);
    spectrostream_decoder_destroy(h);
    return 0;
}

static int test_null_handle(void) {
    printf("TEST: null handle safety... ");

    const char* err = spectrostream_decoder_last_error(NULL);
    if (!err) {
        printf("FAIL (null returned for null handle)\n");
        return 1;
    }

    spectrostream_decoder_destroy(NULL);

    printf("OK\n");
    return 0;
}

int main(int argc, char* argv[]) {
    if (argc < 5) {
        fprintf(stderr, "Usage: %s <model> <codebooks> <window> <sst>\n", argv[0]);
        return 1;
    }

    const char* model = argv[1];
    const char* codebooks = argv[2];
    const char* window = argv[3];
    const char* sst = argv[4];

    printf("=== C ABI Smoke Test ===\n");
    printf("Model:     %s\n", model);
    printf("Codebooks: %s\n", codebooks);
    printf("Window:    %s\n", window);
    printf("SST:       %s\n", sst);
    printf("\n");

    int failures = 0;

    failures += test_null_handle();
    failures += test_error_handling();
    failures += test_create_destroy(model, codebooks, window);
    failures += test_decode(model, codebooks, window, sst);
    failures += test_double_decode(model, codebooks, window, sst);
    failures += test_stream_decode(model, codebooks, window, sst);

    printf("\n");
    if (failures == 0) {
        printf("ALL TESTS PASSED\n");
    } else {
        printf("FAILURES: %d\n", failures);
    }
    return failures;
}
