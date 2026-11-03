# Synthetic frame delivery benchmark

`frame_ipc.py` exercises a candidate local camera-service transport without
opening a camera, binding a socket, displaying windows, or modifying application
configuration. Requires the existing NumPy and OpenCV installations.

```bash
python benchmarks/frame_ipc.py --output benchmarks/results/local.json
```

The default matrix is 640x480, 1280x720, and 1920x1080 BGR frames at 30 FPS:

| Pattern | Content |
| --- | --- |
| `flat` | Solid gray with an embedded sequence number |
| `structured` | Grid, moving rectangle, and changing text |
| `noise16` | Independent random colors in 16x16 pixel blocks |
| `noise4` | Independent random colors in 4x4 pixel blocks |
| `white_noise` | Independent uniform random values for every pixel/channel |

Noise is regenerated for every frame with a reproducible random seed. All
patterns have the same raw byte count at each resolution. Increasing spatial
noise should primarily change compression cost, not raw transport size.

Each case runs for six measured seconds after 0.5 seconds of warmup. There
are two modes: one raw receiver, or that same receiver plus an independent
JPEG encode/decode worker (quality 80). The latter approximates a competing
network codec workload; it does **not** measure network or browser latency.
Decode is included as extra stress; an actual streaming server may only encode.

## What is measured

- **Delivery:** synthetic source ready to a complete private copy in the raw
  receiver, including producer lock/copy, wakeup, contention and receiver copy.
- **Publication-to-copy:** after shared-memory publication to receiver copy done.
- **Generation, copy, JPEG encode/decode, and CRC costs:** reported separately.
- **CPU:** sum of producer and consumer process CPU, as a percentage of one
  logical core (100% means one core, not the whole host).
- **Throughput:** frames published/received, missed publisher slots, skipped
  frames in each latest-frame consumer, and effective publication FPS.
- **Integrity:** full-frame CRC, increasing sequence IDs, and embedded frame tags.
- **Linux host:** average CPU busy percentage and available memory.

Source-ready timestamps exclude synthetic generation and CRC calculation.
Each receiver checks CRC **after** recording delivery time. CPU totals include
generation and CRC overhead. Capture exposure, USB/driver buffering, actual
marker detection, telemetry scheduling, and network transport are not measured.

The shared slot is protected during publication and local snapshots. Readers
consume the newest frame and skip overwritten frames; a slow encoder cannot
grow a backlog. Workers use the spawn start method, so parent/children share
one resource tracker. Discovery and cleanup between independently launched
services still need separate implementation and testing.

## Running on the occupied lab desktop

Use the existing virtual environment; no dependency installs are needed:

```bash
nice -n 19 .venv/bin/python benchmarks/frame_ipc.py \
  --seconds 6 --output /tmp/frame-ipc-desktop.json
```

All workers lower their priority and OpenCV/BLAS thread counts. Cases run
sequentially with frame pacing (no busy-spin). On Linux the script stops before
the next case if measured host CPU exceeds 85%, and it refuses a case if less
than 1 GiB of memory is available. It does not restart or signal any production
process. Shared-memory names are generated for each case and cleaned up by the
benchmark owner.

These controls reduce interference, but background work can still compete for
CPU and memory bandwidth. Inspect host headroom before running. Host load can
also affect the measured tail latencies.

Useful smaller runs:

```bash
# Smoke test
python benchmarks/frame_ipc.py --resolutions 320x240 --patterns flat white_noise \
  --seconds 1 --output benchmarks/results/smoke.json

# Slow consumer: should skip frames without accumulating old ones
python benchmarks/frame_ipc.py --resolutions 640x480 --patterns white_noise \
  --modes raw --consumer-delay-ms 100 --seconds 3 \
  --p99-target-ms 150 \
  --output benchmarks/results/slow.json
```

The slow-consumer test has an intentionally relaxed bound: a consumer sleeping
for 100 ms can receive the final published frame after the producer stops.
Its purpose is to check skipped sequences and bounded age instead of a growing
FIFO backlog. It does not establish a sub-10-ms guarantee for slow consumers.

Results are checkpointed after each case. Exit 0 means every raw-receiver p99
was below the default 10 ms target and all integrity checks passed. Exit 2 means
the latency target was missed; runtime/safety errors exit nonzero and leave the
partial report. This is a short feasibility screen, not a worst-case latency
guarantee. Sample counts and maximum latency must be considered alongside p99.

Machine-specific JSON reports and logs belong in ignored `benchmarks/results/`.

Generate the detailed Markdown comparison and per-case CSV after copying the
completed desktop JSON back to the laptop:

```bash
python benchmarks/summarize_frame_ipc.py \
  benchmarks/results/laptop_matrix.json benchmarks/results/desktop_matrix.json \
  --output benchmarks/results/comparison.md
```

For the occupied-desktop comparison, the benchmark was launched in a separate
transient user service with `Nice=19`, `CPUWeight=1`, `CPUQuota=100%` (one CPU
core total), `MemoryMax=512M`, `TasksMax=48`, and `RuntimeMaxSec=480`. That CPU
cap can introduce additional latency or reduce frame rates during codec-heavy
cases. Results from that constrained run must be labelled accordingly.
