#pragma once

namespace spectrostream {

/**
 * Restrict the calling thread to at most [num_cores] CPUs.
 *
 * Threads created later by TFLite/XNNPACK inherit the affinity mask.  The
 * highest-numbered allowed CPUs are preferred, which on big.LITTLE Android
 * SoCs usually means the performance cores.  Passing 0 (or a value >= the
 * number of allowed CPUs) restores the full allowed set.
 *
 * Returns 0 on success or when affinity is unavailable, -1 if the kernel
 * rejected the request.
 */
int set_current_thread_affinity(int num_cores);

}  // namespace spectrostream
