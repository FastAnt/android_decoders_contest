#pragma once

#include <memory>
#include <string>
#include <vector>

namespace spectrostream {

class Istft {
public:
    static constexpr int kFftSize = 960;
    static constexpr int kFreqBins = 481;
    static constexpr int kHopSize = 480;
    static constexpr int kWindowSize = 960;
    static constexpr int kChannels = 2;
    static constexpr int kSampleRate = 48000;
    static constexpr int kStftFramesPerCodecFrame = 4;

    explicit Istft(const std::string& window_path);
    ~Istft();

    Istft(const Istft&) = delete;
    Istft& operator=(const Istft&) = delete;
    Istft(Istft&&) noexcept;
    Istft& operator=(Istft&&) noexcept;

    // Process spectrum with arbitrary number of STFT frames.
    // Input: spectrum [2, stft_frames, 481, 2] (channel, frame, freq_bin, real/imag)
    // Output: interleaved stereo PCM. Length depends on stft_frames.
    // target_samples: how many samples per channel to produce (truncates OLA output).
    std::vector<float> synthesize(const float* spectrum, int stft_frames,
                                  int target_samples) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace spectrostream
