"""Paced, camera-free frame IPC benchmark. No sockets or production resources."""

import os

# Avoid BLAS/OpenCV thread pools competing with an occupied lab machine.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

import argparse
import ctypes
import json
import multiprocessing as mp
from multiprocessing import shared_memory
from pathlib import Path
import platform
import queue
import time
import traceback
import zlib

import cv2
import numpy as np


PATTERNS = ("flat", "structured", "noise16", "noise4", "white_noise")


def low_priority():
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise ctypes.WinError(ctypes.get_last_error())
    elif hasattr(os, "nice"):
        os.nice(19)
    cv2.setNumThreads(1)


def distribution(values, factor=1.0):
    if not values:
        return None
    array = np.asarray(values, np.float64) * factor
    return {
        "n": len(values),
        "min": float(array.min()),
        "median": float(np.median(array)),
        "p95": float(np.percentile(array, 95)),
        "p99": float(np.percentile(array, 99)),
        "max": float(array.max()),
        "mean": float(array.mean()),
    }


def host_snapshot():
    """Read-only Linux host counters. No camera/other process inspection."""
    if platform.system() != "Linux":
        return None
    fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:9]
    ticks = list(map(int, fields))
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {
        "total": sum(ticks), "idle": ticks[3] + ticks[4],
        "available_mb": int(memory["MemAvailable"].split()[0]) / 1024,
    }


def consumer(name, shape, condition, meta, ready, results, start_at, role,
             jpeg_quality, delay_ms):
    """Snapshot newest frame under the lock; all expensive work happens outside."""
    shm = None
    try:
        low_priority()
        shm = shared_memory.SharedMemory(name=name)
        source = np.ndarray(shape, np.uint8, buffer=shm.buf)
        local = np.empty(shape, np.uint8)
        ready.set()
        last = 0
        delivery, publication_to_copy, copy_times = [], [], []
        encode_times, decode_times, jpeg_sizes, checksum_times = [], [], [], []
        skipped = received = corrupt = invalid_order = 0
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        while True:
            with condition:
                changed = condition.wait_for(lambda: meta[0] != last or meta[3], timeout=2)
                if not changed:
                    raise TimeoutError("Producer stopped publishing without signalling shutdown")
                if meta[0] == last:
                    break
                sequence, captured, published, _, checksum = list(meta)
                copy_start = time.perf_counter_ns()
                np.copyto(local, source)
                copied = time.perf_counter_ns()
            measured = captured >= start_at.value
            if measured:
                if last:
                    skipped += max(0, sequence - last - 1)
                invalid_order += int(sequence <= last)
                received += 1
                delivery.append(copied - captured)
                publication_to_copy.append(copied - published)
                copy_times.append(copied - copy_start)
            last = sequence
            check_start = time.perf_counter_ns()
            matches = zlib.crc32(local) == checksum
            if measured:
                corrupt += int(not matches)
                checksum_times.append(time.perf_counter_ns() - check_start)
            if not matches:
                raise RuntimeError("Frame CRC does not match its sequence metadata")
            if role == "jpeg":
                encode_start = time.perf_counter_ns()
                ok, encoded = cv2.imencode(".jpg", local, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                encoded_at = time.perf_counter_ns()
                if not ok:
                    raise RuntimeError("JPEG encode failed")
                if measured:
                    encode_times.append(encoded_at - encode_start)
                    jpeg_sizes.append(encoded.nbytes)
                # Include a local decode to estimate codec cost, not network latency.
                decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
                if decoded is None or decoded.shape != shape:
                    raise RuntimeError("JPEG decode failed")
                if measured:
                    decode_times.append(time.perf_counter_ns() - encoded_at)
            elif delay_ms:
                time.sleep(delay_ms / 1000)
        elapsed = time.perf_counter() - wall_start
        results.put({
            "role": role, "received": received, "skipped": skipped,
            "integrity_errors": corrupt, "order_errors": invalid_order,
            "cpu_seconds": time.process_time() - cpu_start,
            "worker_wall_seconds": elapsed,
            "delivery_ms": distribution(delivery, 1e-6),
            "publication_to_copy_ms": distribution(publication_to_copy, 1e-6),
            "reader_copy_ms": distribution(copy_times, 1e-6),
            "crc_ms": distribution(checksum_times, 1e-6),
            "jpeg_encode_ms": distribution(encode_times, 1e-6),
            "jpeg_decode_ms": distribution(decode_times, 1e-6),
            "jpeg_bytes": distribution(jpeg_sizes),
        })
        del source, local
    except BaseException:
        results.put({"role": role, "error": traceback.format_exc()})
        raise
    finally:
        if shm is not None:
            shm.close()


def generate_frame(pattern, shape, sequence, rng):
    height, width, _ = shape
    if pattern == "flat":
        image = np.full(shape, 200, np.uint8)
    elif pattern == "structured":
        image = np.full(shape, 245, np.uint8)
        for x in range(0, width, 64):
            cv2.line(image, (x, 0), (x, height - 1), (170, 170, 170), 1)
        for y in range(0, height, 64):
            cv2.line(image, (0, y), (width - 1, y), (170, 170, 170), 1)
        x, y = (sequence * 7) % (width - 80), (sequence * 3) % (height - 80)
        cv2.rectangle(image, (x, y), (x + 64, y + 64), (20, 70, 160), -1)
        cv2.putText(image, str(sequence), (20, height // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    1.5, (0, 0, 0), 3)
    else:
        block = {"noise16": 16, "noise4": 4, "white_noise": 1}[pattern]
        image = rng.integers(0, 256, (max(1, height // block), max(1, width // block), 3), np.uint8)
        if block != 1:
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_NEAREST)
    # A frame number at both ends also exercises dynamic data in simple frames.
    tag = np.frombuffer(sequence.to_bytes(8, "little"), np.uint8)
    image.reshape(-1)[:8] = tag
    image.reshape(-1)[-8:] = tag
    return image


def run_case(args, width, height, pattern, mode):
    ctx = mp.get_context("spawn")
    shape = (height, width, 3)
    shm = shared_memory.SharedMemory(create=True, size=width * height * 3)
    pixels = np.ndarray(shape, np.uint8, buffer=shm.buf)
    condition = ctx.Condition()
    # sequence, source-ready timestamp, publication timestamp, done, frame CRC
    meta = ctx.RawArray("Q", 5)
    start_at = ctx.Value("Q", 0)
    results = ctx.Queue()
    workers = []
    initial_host = host_snapshot()
    if initial_host and initial_host["available_mb"] < args.min_free_mb:
        del pixels
        shm.close()
        shm.unlink()
        raise RuntimeError("Insufficient free host memory; benchmark stopped")
    try:
        for role in (["raw", "jpeg"] if mode == "with_jpeg" else ["raw"]):
            ready = ctx.Event()
            process = ctx.Process(target=consumer, args=(
                shm.name, shape, condition, meta, ready, results, start_at, role,
                args.jpeg_quality, args.consumer_delay_ms,
            ))
            process.start()
            workers.append((process, ready))
        for process, ready in workers:
            if not ready.wait(15) or not process.is_alive():
                raise RuntimeError("Consumer did not become ready")
        start = time.perf_counter_ns()
        start_at.value = start + int(args.warmup * 1e9)
        finish = start_at.value + int(args.seconds * 1e9)
        period = round(1e9 / args.fps)
        deadline = start
        sequence = measured_published = late_slots = 0
        generation, publish_times = [], []
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        rng = np.random.default_rng(42)
        while time.perf_counter_ns() < finish:
            remaining = (deadline - time.perf_counter_ns()) / 1e9
            if remaining > 0:
                time.sleep(remaining)
            now = time.perf_counter_ns()
            if now >= finish:
                break
            if now - deadline >= period:
                late_slots += (now - deadline) // period
                deadline = now
            sequence += 1
            generated_at = time.perf_counter_ns()
            image = generate_frame(pattern, shape, sequence, rng)
            generated = time.perf_counter_ns()
            checksum = zlib.crc32(image)
            # Simulate camera.read() returning a complete usable raw image.
            captured = time.perf_counter_ns()
            with condition:
                np.copyto(pixels, image)
                meta[0], meta[1], meta[4] = sequence, captured, checksum
                meta[2] = time.perf_counter_ns()
                condition.notify_all()
            if captured >= start_at.value:
                measured_published += 1
                generation.append(generated - generated_at)
                publish_times.append(meta[2] - captured)
            deadline += period
        with condition:
            meta[3] = 1
            condition.notify_all()
        producer_cpu = time.process_time() - cpu_start
        wall = time.perf_counter() - wall_start
        outputs = [results.get(timeout=15) for _ in workers]
        for process, _ in workers:
            process.join(5)
            if process.is_alive() or process.exitcode != 0:
                raise RuntimeError("Consumer exited abnormally")
        for output in outputs:
            if "error" in output:
                raise RuntimeError(output["error"])
            if not output["received"]:
                raise RuntimeError("Consumer received no measured frames")
        final_host = host_snapshot()
        host_busy = None
        if initial_host and final_host:
            total = final_host["total"] - initial_host["total"]
            idle = final_host["idle"] - initial_host["idle"]
            host_busy = 100 * (1 - idle / total) if total else None
        return {
            "resolution": f"{width}x{height}", "frame_bytes": pixels.nbytes,
            "pattern": pattern, "mode": mode, "target_fps": args.fps,
            "duration_seconds": args.seconds, "warmup_seconds": args.warmup,
            "published": measured_published,
            "effective_publisher_fps": measured_published / args.seconds,
            "publisher_late_slots": late_slots,
            "generation_ms": distribution(generation, 1e-6),
            "publication_ms": distribution(publish_times, 1e-6),
            "cpu_one_core_percent": 100 * (producer_cpu + sum(o["cpu_seconds"] for o in outputs)) / wall,
            "host_busy_percent": host_busy,
            "host_available_mb": final_host["available_mb"] if final_host else None,
            "consumers": {o["role"]: o for o in outputs},
        }
    finally:
        with condition:
            meta[3] = 1
            condition.notify_all()
        for process, _ in workers:
            process.join(2)
            if process.is_alive():
                process.terminate()  # Only children created by this benchmark.
                process.join(3)
        results.close()
        del pixels
        shm.close()
        shm.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolutions", nargs="+", default=["640x480", "1280x720", "1920x1080"])
    parser.add_argument("--patterns", nargs="+", choices=PATTERNS, default=list(PATTERNS))
    parser.add_argument("--modes", nargs="+", choices=["raw", "with_jpeg"], default=["raw", "with_jpeg"])
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--warmup", type=float, default=0.5)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument("--consumer-delay-ms", type=float, default=0)
    parser.add_argument("--min-free-mb", type=int, default=1024)
    parser.add_argument("--max-host-cpu", type=float, default=85)
    parser.add_argument("--p99-target-ms", type=float, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.seconds <= 0 or args.warmup < 0 or args.fps <= 0
            or args.consumer_delay_ms < 0 or not 1 <= args.jpeg_quality <= 100):
        parser.error("Invalid duration, rate, delay or JPEG quality")
    sizes = []
    for value in args.resolutions:
        try:
            width, height = map(int, value.lower().split("x"))
            if not (96 <= width <= 3840 and 96 <= height <= 2160):
                raise ValueError()
            sizes.append((width, height))
        except ValueError:
            parser.error(f"Invalid resolution: {value}")
    low_priority()
    report = {
        "platform": platform.platform(), "python": platform.python_version(),
        "numpy": np.__version__, "opencv": cv2.__version__, "cpu_count": os.cpu_count(),
        "priority": "below_normal" if os.name == "nt" else "nice19",
        "clock": "perf_counter_ns, shared system monotonic clock",
        "notes": [
            "Synthetic data only; no camera, sockets, GUI or production files.",
            "Delivery includes publication lock/copy, wakeup and receiver copy; excludes generation and CRC.",
            "JPEG mode adds a separate latest-frame consumer doing encode+decode; no network transport.",
            "Consumers are spawn children sharing one resource tracker; not independently launched services.",
            "CPU percent is summed worker CPU; 100% equals one core. CRC overhead is included in CPU.",
        ],
        "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    try:
        for mode in args.modes:
            for width, height in sizes:
                for pattern in args.patterns:
                    print(f"Running {width}x{height} {pattern} {mode}...", flush=True)
                    case = run_case(args, width, height, pattern, mode)
                    report["cases"].append(case)
                    save()
                    raw = case["consumers"]["raw"]
                    print(f"  n={raw['received']} median={raw['delivery_ms']['median']:.3f} "
                          f"p99={raw['delivery_ms']['p99']:.3f} max={raw['delivery_ms']['max']:.3f} ms "
                          f"skipped={raw['skipped']} CPU={case['cpu_one_core_percent']:.1f}% of one core", flush=True)
                    if case["host_busy_percent"] is not None and case["host_busy_percent"] > args.max_host_cpu:
                        raise RuntimeError("Host CPU exceeded safety threshold; stopped before the next case")
    except BaseException:
        report["error"] = traceback.format_exc()
        save()
        raise
    report["passed"] = all(
        case["consumers"]["raw"]["delivery_ms"]["p99"] < args.p99_target_ms
        and all(c["integrity_errors"] == 0 and c["order_errors"] == 0 for c in case["consumers"].values())
        for case in report["cases"]
    )
    save()
    print(f"{'PASS' if report['passed'] else 'TARGET MISSED'}: results in {args.output}", flush=True)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
