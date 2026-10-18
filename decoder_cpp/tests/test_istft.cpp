#include "spectrostream/istft.h"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>

int main() {
    const char* window_path = "models/istft_window_f960.f32";

    std::printf("Testing Istft\n");

    try {
        spectrostream::Istft istft(window_path);

        // Create a test spectrum: single tone at bin 10
        // spectrum layout: [2 channels][100 frames][481 bins][2 real/imag]
        const int total = 2 * 100 * 481 * 2;
        std::vector<float> spectrum(total, 0.0f);

        // Put a cosine at bin 10 for channel 0 (all frames, amplitude 1.0)
        for (int frame = 0; frame < 100; ++frame) {
            int idx = (0 * 100 * 481 * 2) + (frame * 481 * 2) + (10 * 2);
            spectrum[idx] = 1.0f;      // real
            spectrum[idx + 1] = 0.0f;  // imag
        }

        auto pcm = istft.synthesize(spectrum.data(), 100, 48000);

        assert(pcm.size() == 48000u * 2u);

        // Verify finite
        for (size_t i = 0; i < pcm.size(); ++i) {
            assert(std::isfinite(pcm[i]));
        }

        // Channel 0 should have non-zero energy (tone at bin 10)
        double energy_ch0 = 0.0;
        for (int i = 0; i < 48000; ++i) {
            energy_ch0 += pcm[i * 2] * pcm[i * 2];
        }

        // Channel 1 should be silent
        double energy_ch1 = 0.0;
        for (int i = 0; i < 48000; ++i) {
            energy_ch1 += pcm[i * 2 + 1] * pcm[i * 2 + 1];
        }

        std::printf("  Channel 0 energy: %.6f\n", energy_ch0);
        std::printf("  Channel 1 energy: %.6f\n", energy_ch1);

        assert(energy_ch0 > 0.0);
        assert(energy_ch1 < 1e-10);

        std::printf("PASS: Istft\n");
    } catch (const std::exception& e) {
        std::fprintf(stderr, "FAIL: %s\n", e.what());
        return 1;
    }

    return 0;
}
