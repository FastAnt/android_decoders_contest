#include "spectrostream/wav_writer.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

namespace spectrostream {

bool write_wav(const std::string& path,
               const float* pcm,
               int64_t total_samples,
               int32_t sample_rate,
               int16_t channels) {

    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;

    const uint16_t bits_per_sample = 16;
    const uint16_t block_align = channels * (bits_per_sample / 8);
    const uint32_t byte_rate = static_cast<uint32_t>(sample_rate) * block_align;
    const uint32_t data_size = static_cast<uint32_t>(total_samples) * (bits_per_sample / 8);
    const uint32_t file_size = 36 + data_size;

    // RIFF header
    std::fwrite("RIFF", 1, 4, f);
    std::fwrite(&file_size, 4, 1, f);
    std::fwrite("WAVE", 1, 4, f);

    // fmt chunk
    std::fwrite("fmt ", 1, 4, f);
    uint32_t fmt_size = 16;
    uint16_t audio_format = 1;  // PCM
    uint16_t ch = static_cast<uint16_t>(channels);
    uint32_t sr = static_cast<uint32_t>(sample_rate);
    std::fwrite(&fmt_size, 4, 1, f);
    std::fwrite(&audio_format, 2, 1, f);
    std::fwrite(&ch, 2, 1, f);
    std::fwrite(&sr, 4, 1, f);
    std::fwrite(&byte_rate, 4, 1, f);
    std::fwrite(&block_align, 2, 1, f);
    std::fwrite(&bits_per_sample, 2, 1, f);

    // data chunk
    std::fwrite("data", 1, 4, f);
    std::fwrite(&data_size, 4, 1, f);

    // Convert float [-1,1] to int16 with clipping
    for (int64_t i = 0; i < total_samples; ++i) {
        float s = std::clamp(pcm[i], -1.0f, 1.0f);
        int16_t sample = static_cast<int16_t>(s * 32767.0f);
        std::fwrite(&sample, 2, 1, f);
    }

    std::fclose(f);
    return true;
}

}  // namespace spectrostream
