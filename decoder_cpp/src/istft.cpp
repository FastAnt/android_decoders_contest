#include "spectrostream/istft.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>

#include "pocketfft_hdronly.h"

namespace spectrostream {

struct Istft::Impl {
    std::vector<float> window;  // [kFftSize]
};

Istft::Istft(const std::string& window_path) : impl_(std::make_unique<Impl>()) {
    FILE* f = std::fopen(window_path.c_str(), "rb");
    if (!f) throw std::runtime_error("Cannot open window file: " + window_path);

    std::fseek(f, 0, SEEK_END);
    long file_size = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);

    if (file_size != kWindowSize * static_cast<long>(sizeof(float))) {
        std::fclose(f);
        throw std::runtime_error("Window file size mismatch: expected " +
                                 std::to_string(kWindowSize * sizeof(float)) +
                                 " bytes, got " + std::to_string(file_size));
    }

    impl_->window.resize(kWindowSize);
    size_t read = std::fread(impl_->window.data(), sizeof(float), kWindowSize, f);
    std::fclose(f);

    if (read != static_cast<size_t>(kWindowSize)) {
        throw std::runtime_error("Short read on window file");
    }
}

Istft::~Istft() = default;
Istft::Istft(Istft&&) noexcept = default;
Istft& Istft::operator=(Istft&&) noexcept = default;

std::vector<float> Istft::synthesize(const float* spectrum, int stft_frames,
                                     int target_samples) const {
    // spectrum layout: [2 channels][stft_frames][481 bins][2 real/imag]
    const int full_ola_samples = (stft_frames - 1) * kHopSize + kFftSize;

    if (target_samples > full_ola_samples) {
        throw std::runtime_error("target_samples exceeds OLA output length");
    }

    std::vector<float> output(target_samples * kChannels);

    pocketfft::shape_t shape_r = {static_cast<size_t>(kFftSize)};
    pocketfft::stride_t stride_c = {static_cast<ptrdiff_t>(sizeof(std::complex<float>))};
    pocketfft::stride_t stride_r = {static_cast<ptrdiff_t>(sizeof(float))};
    pocketfft::shape_t axes = {0};

    std::vector<std::complex<float>> freq_buf(kFreqBins);
    std::vector<float> time_buf(kFftSize);
    std::vector<float> ola_buf(full_ola_samples, 0.0f);

    for (int ch = 0; ch < kChannels; ++ch) {
        std::fill(ola_buf.begin(), ola_buf.end(), 0.0f);

        const float* ch_spectrum = spectrum +
            static_cast<size_t>(ch) * stft_frames * kFreqBins * 2;

        for (int frame = 0; frame < stft_frames; ++frame) {
            const float* frame_data = ch_spectrum +
                static_cast<size_t>(frame) * kFreqBins * 2;

            for (int bin = 0; bin < kFreqBins; ++bin) {
                freq_buf[bin] = std::complex<float>(
                    frame_data[bin * 2], frame_data[bin * 2 + 1]);
            }

            pocketfft::c2r(
                shape_r,
                stride_c,
                stride_r,
                axes,
                pocketfft::BACKWARD,
                freq_buf.data(),
                time_buf.data(),
                1.0f / static_cast<float>(kFftSize));

            int ola_offset = frame * kHopSize;
            for (int i = 0; i < kFftSize; ++i) {
                ola_buf[ola_offset + i] += time_buf[i] * impl_->window[i];
            }
        }

        // Take the first target_samples from OLA output
        for (int i = 0; i < target_samples; ++i) {
            output[i * kChannels + ch] = ola_buf[i];
        }
    }

    return output;
}

}  // namespace spectrostream
