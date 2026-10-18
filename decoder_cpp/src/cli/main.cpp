#include "spectrostream/decoder.h"
#include "spectrostream/sst_reader.h"
#include "spectrostream/wav_writer.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace {

struct Args {
    std::string model_path;
    std::string codebooks_path;
    std::string window_path;
    std::string input_path;
    std::string output_path = "reconstructed_cpp.wav";
    int threads = 4;
    bool inspect_only = false;
    bool use_gpu = false;
    int benchmark_runs = 0;
};

void print_usage(const char* prog) {
    std::fprintf(stderr,
        "Usage: %s [options]\n"
        "\n"
        "Options:\n"
        "  --model <path>       TFLite model file (required)\n"
        "  --codebooks <path>   RVQ codebooks .f32 file (required)\n"
        "  --window <path>      iSTFT window .f32 file (required)\n"
        "  --input <path>       Input .sst file (required)\n"
        "  --output <path>      Output .wav file (default: reconstructed_cpp.wav)\n"
        "  --threads <N>        CPU threads (default: 4)\n"
        "  --gpu                Use GPU delegate (requires build with ENABLE_GPU_DELEGATE)\n"
        "  --benchmark <N>      Run decode N times and report avg/min/max RTF\n"
        "  --inspect            Only inspect .sst, do not decode\n"
        "  --help               Show this message\n",
        prog);
}

bool parse_args(int argc, char* argv[], Args& args) {
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            std::exit(0);
        } else if (arg == "--model" && i + 1 < argc) {
            args.model_path = argv[++i];
        } else if (arg == "--codebooks" && i + 1 < argc) {
            args.codebooks_path = argv[++i];
        } else if (arg == "--window" && i + 1 < argc) {
            args.window_path = argv[++i];
        } else if (arg == "--input" && i + 1 < argc) {
            args.input_path = argv[++i];
        } else if (arg == "--output" && i + 1 < argc) {
            args.output_path = argv[++i];
        } else if (arg == "--threads" && i + 1 < argc) {
            args.threads = std::atoi(argv[++i]);
        } else if (arg == "--gpu") {
            args.use_gpu = true;
        } else if (arg == "--benchmark" && i + 1 < argc) {
            args.benchmark_runs = std::atoi(argv[++i]);
        } else if (arg == "--inspect") {
            args.inspect_only = true;
        } else {
            std::fprintf(stderr, "Unknown argument: %s\n", arg.c_str());
            return false;
        }
    }
    return true;
}

void run_inspect(const std::string& path) {
    auto info = spectrostream::inspect_sst(path);
    std::printf("=== SST1 Inspection ===\n");
    std::printf("File:             %s\n", path.c_str());
    std::printf("Sample rate:      %u Hz\n", info.header.sample_rate);
    std::printf("Channels:         %u\n", info.header.channels);
    std::printf("Frame rate:       %u fps\n", info.header.frame_rate);
    std::printf("RVQ depth:        %u\n", info.header.max_rvq_depth);
    std::printf("Bits per code:    %u\n", info.header.bits_per_code);
    std::printf("Chunk frames:     %u\n", info.header.chunk_frames);
    std::printf("Total frames:     %u\n", info.header.total_frame_count);
    std::printf("Original samples: %lu\n", static_cast<unsigned long>(info.header.original_samples));
    std::printf("Chunk count:      %u\n", info.header.chunk_count);
    std::printf("Layout:           %u (codebook-major)\n", info.header.layout);
    std::printf("Payload bytes:    %u\n", info.total_payload_bytes);
    std::printf("Duration:         %.3f s\n", info.duration_seconds);
    std::printf("Token range:      [%u, %u]\n", info.min_token, info.max_token);
    std::printf("CRC status:       %s\n", info.all_crcs_valid ? "OK" : "FAILED");
}

}  // namespace

int main(int argc, char* argv[]) {
    Args args;
    if (!parse_args(argc, argv, args)) {
        print_usage(argv[0]);
        return 1;
    }

    if (args.input_path.empty()) {
        std::fprintf(stderr, "Error: --input is required\n");
        print_usage(argv[0]);
        return 1;
    }

    if (args.inspect_only) {
        try {
            run_inspect(args.input_path);
            return 0;
        } catch (const std::exception& e) {
            std::fprintf(stderr, "Error: %s\n", e.what());
            return 1;
        }
    }

    if (args.model_path.empty() || args.codebooks_path.empty() || args.window_path.empty()) {
        std::fprintf(stderr, "Error: --model, --codebooks, and --window are required for decoding\n");
        print_usage(argv[0]);
        return 1;
    }

    try {
        std::printf("SpectroStream C++ Decoder\n");
        std::printf("========================\n");

        auto t_start = std::chrono::high_resolution_clock::now();

        std::printf("Loading model: %s\n", args.model_path.c_str());
        std::printf("Codebooks:     %s\n", args.codebooks_path.c_str());
        std::printf("Window:        %s\n", args.window_path.c_str());
        std::printf("Input:         %s\n", args.input_path.c_str());
        std::printf("Output:        %s\n", args.output_path.c_str());
        std::printf("Threads:       %d\n", args.threads);
        std::printf("\n");

        auto t_load = std::chrono::high_resolution_clock::now();

        spectrostream::DecoderConfig config;
        config.model_path = args.model_path;
        config.codebooks_path = args.codebooks_path;
        config.window_path = args.window_path;
        config.num_threads = args.threads;
        config.use_xnnpack = !args.use_gpu;
        config.use_gpu = args.use_gpu;

        spectrostream::Decoder decoder(config);

        auto t_loaded = std::chrono::high_resolution_clock::now();
        double load_ms = std::chrono::duration<double, std::milli>(t_loaded - t_load).count();
        std::printf("Model + assets loaded in %.1f ms\n", load_ms);
        std::printf("Backend: %s\n", args.use_gpu ? "GPU" : "XNNPACK CPU");

        auto result = decoder.decode_file(args.input_path);

        std::printf("\n=== Decode Timing ===\n");
        std::printf("SST parse:      %8.1f ms\n", result.sst_parse_ms);
        std::printf("RVQ dequant:    %8.1f ms\n", result.rvq_ms);
        std::printf("LiteRT infer:   %8.1f ms\n", result.inference_ms);
        std::printf("iSTFT:          %8.1f ms\n", result.istft_ms);
        std::printf("Total decode:   %8.1f ms\n", result.total_ms);
        std::printf("\n");
        std::printf("Audio duration: %.3f s\n", result.audio_duration_s);
        std::printf("RTF:            %.4f\n", result.rtf);
        std::printf("Sample rate:    %d Hz\n", result.sample_rate);
        std::printf("Channels:       %d\n", result.channels);
        std::printf("PCM frames:     %ld\n", static_cast<long>(result.frame_count));
        std::printf("\n");

        // Benchmark mode: repeat decode N times
        if (args.benchmark_runs > 1) {
            std::printf("=== Benchmark: %d runs ===\n", args.benchmark_runs);
            double min_rtf = result.rtf;
            double max_rtf = result.rtf;
            double sum_rtf = result.rtf;
            double min_infer = result.inference_ms;
            double max_infer = result.inference_ms;

            for (int run = 1; run < args.benchmark_runs; ++run) {
                auto r = decoder.decode_file(args.input_path);
                sum_rtf += r.rtf;
                if (r.rtf < min_rtf) min_rtf = r.rtf;
                if (r.rtf > max_rtf) max_rtf = r.rtf;
                if (r.inference_ms < min_infer) min_infer = r.inference_ms;
                if (r.inference_ms > max_infer) max_infer = r.inference_ms;
                std::printf("  Run %d: RTF=%.4f  infer=%.1f ms\n",
                            run + 1, r.rtf, r.inference_ms);
            }

            std::printf("\nBenchmark Summary (%d runs):\n", args.benchmark_runs);
            std::printf("  RTF:   min=%.4f  avg=%.4f  max=%.4f\n",
                        min_rtf, sum_rtf / args.benchmark_runs, max_rtf);
            std::printf("  Infer: min=%.1f ms  max=%.1f ms\n", min_infer, max_infer);
            std::printf("\n");
        }

        // Write WAV
        int64_t total_samples = static_cast<int64_t>(result.pcm.size());
        bool ok = spectrostream::write_wav(
            args.output_path,
            result.pcm.data(),
            total_samples,
            result.sample_rate,
            static_cast<int16_t>(result.channels));

        if (!ok) {
            std::fprintf(stderr, "Error: Failed to write WAV file\n");
            return 1;
        }

        auto t_end = std::chrono::high_resolution_clock::now();
        double total_wall_ms = std::chrono::duration<double, std::milli>(t_end - t_start).count();

        std::printf("Written: %s (PCM16 stereo 48kHz)\n", args.output_path.c_str());
        std::printf("Total wall time: %.1f ms\n", total_wall_ms);

        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "Error: %s\n", e.what());
        return 1;
    }
}
