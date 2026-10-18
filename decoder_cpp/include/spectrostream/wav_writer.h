#pragma once

#include <cstdint>
#include <string>

namespace spectrostream {

// Write interleaved float32 PCM to a PCM16 WAV file.
// Returns true on success.
bool write_wav(const std::string& path,
               const float* pcm,
               int64_t total_samples,  // total interleaved samples
               int32_t sample_rate,
               int16_t channels);

}  // namespace spectrostream
