#include "spectrostream/rvq_dequantizer.h"
#include "spectrostream/sst_reader.h"

#include <cassert>
#include <cmath>
#include <cstdio>

int main() {
    const char* codebook_path = "models/rvq_codebooks.f32";
    const char* sst_path = "../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/"
                           "069569e7525fdd1e462b9f5b1a394a9f.sst";

    std::printf("Testing RvqDequantizer\n");

    try {
        spectrostream::RvqDequantizer dequant(codebook_path);
        auto tokens = spectrostream::read_sst(sst_path);

        // Dequantize first 25 frames
        auto embeddings = dequant.dequantize(
            tokens.tokens.data(), 25, tokens.rvq_depth);

        assert(embeddings.size() == 25 * 256);

        // Verify no NaN/Inf
        for (size_t i = 0; i < embeddings.size(); ++i) {
            assert(std::isfinite(embeddings[i]));
        }

        // Print some stats
        float min_val = embeddings[0], max_val = embeddings[0];
        double sum = 0.0;
        for (float v : embeddings) {
            if (v < min_val) min_val = v;
            if (v > max_val) max_val = v;
            sum += v;
        }
        std::printf("  embedding range: [%.4f, %.4f]\n", min_val, max_val);
        std::printf("  embedding mean:  %.6f\n", sum / embeddings.size());

        std::printf("PASS: RvqDequantizer\n");
    } catch (const std::exception& e) {
        std::fprintf(stderr, "FAIL: %s\n", e.what());
        return 1;
    }

    return 0;
}
