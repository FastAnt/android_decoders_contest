#include "spectrostream/sst_reader.h"

#include <cassert>
#include <cstdio>

int main() {
    const char* sst_path = "../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/"
                           "069569e7525fdd1e462b9f5b1a394a9f.sst";

    std::printf("Testing SstReader on: %s\n", sst_path);

    try {
        auto tokens = spectrostream::read_sst(sst_path);

        std::printf("  sample_rate:     %u\n", tokens.sample_rate);
        std::printf("  codec_frame_rate: %u\n", tokens.codec_frame_rate);
        std::printf("  frame_count:     %u\n", tokens.frame_count);
        std::printf("  rvq_depth:       %u\n", tokens.rvq_depth);
        std::printf("  original_samples: %lu\n",
                    static_cast<unsigned long>(tokens.original_samples));
        std::printf("  tokens.size():   %zu\n", tokens.tokens.size());

        assert(tokens.sample_rate == 48000);
        assert(tokens.codec_frame_rate == 25);
        assert(tokens.frame_count == 4052);
        assert(tokens.rvq_depth == 64);
        assert(tokens.original_samples == 7779614);
        assert(tokens.tokens.size() == 4052u * 64u);

        // Verify all tokens in range
        uint16_t min_tok = 1023, max_tok = 0;
        for (auto t : tokens.tokens) {
            assert(t < 1024);
            if (t < min_tok) min_tok = t;
            if (t > max_tok) max_tok = t;
        }
        std::printf("  token range:     [%u, %u]\n", min_tok, max_tok);

        std::printf("PASS: SstReader\n");
    } catch (const std::exception& e) {
        std::fprintf(stderr, "FAIL: %s\n", e.what());
        return 1;
    }

    // Test inspect
    try {
        auto info = spectrostream::inspect_sst(sst_path);
        assert(info.all_crcs_valid);
        assert(info.header.total_frame_count == 4052);
        std::printf("PASS: inspect_sst\n");
    } catch (const std::exception& e) {
        std::fprintf(stderr, "FAIL inspect: %s\n", e.what());
        return 1;
    }

    return 0;
}
