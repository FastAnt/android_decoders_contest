#include "spectrostream/cpu_affinity.h"

#if defined(__linux__)
#include <sched.h>
#include <unistd.h>

#include <cerrno>
#include <string>
#include <vector>
#endif

#if defined(__ANDROID__)
#include <android/log.h>
#include <jni.h>
#define SS_AFFINITY_LOG(...) \
    __android_log_print(ANDROID_LOG_INFO, "SpectroAffinity", __VA_ARGS__)
#else
#define SS_AFFINITY_LOG(...) ((void)0)
#endif

namespace spectrostream {

#if defined(__linux__)
namespace {

// The process's full CPU set at first use.  Thread affinity is inherited and
// can only be narrowed, so restoring all cores requires this original mask.
const cpu_set_t& original_cpu_set() {
    static const cpu_set_t value = [] {
        cpu_set_t set;
        CPU_ZERO(&set);
        if (sched_getaffinity(0, sizeof(set), &set) != 0) {
            CPU_ZERO(&set);
        }
        return set;
    }();
    return value;
}

}  // namespace
#endif

int set_current_thread_affinity(int num_cores) {
#if defined(__linux__)
    const cpu_set_t& original = original_cpu_set();
    const int original_count = CPU_COUNT(&original);
    if (original_count <= 0) {
        return -1;
    }

    cpu_set_t target;
    CPU_ZERO(&target);

    if (num_cores <= 0 || num_cores >= original_count) {
        target = original;
    } else {
        std::vector<int> cpus;
        for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
            if (CPU_ISSET(cpu, &original)) {
                cpus.push_back(cpu);
            }
        }
        if (cpus.empty()) {
            return -1;
        }
        // Prefer the highest-numbered CPUs (typically the fast cores).
        for (size_t index = cpus.size() - static_cast<size_t>(num_cores);
             index < cpus.size(); ++index) {
            CPU_SET(cpus[index], &target);
        }
    }

    cpu_set_t current;
    CPU_ZERO(&current);
    const int current_result = sched_getaffinity(0, sizeof(current), &current);
    std::string target_list;
    for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
        if (CPU_ISSET(cpu, &target)) {
            if (!target_list.empty()) target_list += ",";
            target_list += std::to_string(cpu);
        }
    }

    errno = 0;
    const int result = sched_setaffinity(0, sizeof(target), &target);
    SS_AFFINITY_LOG(
        "tid=%d requested=%d original=%d current=%d current_result=%d "
        "target=%d [%s] result=%d errno=%d",
        static_cast<int>(gettid()), num_cores, original_count,
        CPU_COUNT(&current), current_result, CPU_COUNT(&target),
        target_list.c_str(), result, errno);
    return result == 0 ? 0 : -1;
#else
    (void)num_cores;
    return 0;
#endif
}

}  // namespace spectrostream

#if defined(__ANDROID__)
extern "C" JNIEXPORT jint JNICALL
Java_com_neuralcodecs_client_1android_SageBridge_nativeSetAffinity(
    JNIEnv*, jobject, jint num_cores) {
    return spectrostream::set_current_thread_affinity(
        static_cast<int>(num_cores));
}
#endif
