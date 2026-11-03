"""Measure the real camera-service IPC using synthetic frames and HTTP viewers."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_stream import stop_owned
from frame_stream import CameraStreamError, SharedFrameReader, descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--resolutions", nargs="+", default=["640x480", "1280x720", "1920x1080"])
    parser.add_argument("--viewers", nargs="+", type=int, default=[0, 2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"cases": []}
    root = Path(__file__).resolve().parents[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for resolution in args.resolutions:
        width, height = map(int, resolution.split("x"))
        for viewer_count in args.viewers:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                with (path / "service.log").open("w+", encoding="utf-8") as log:
                    service = subprocess.Popen(
                        [sys.executable, "-B", str(root / "camera_stream.py"), "--synthetic",
                         "--width", str(width), "--height", str(height), "--stream-dir", directory,
                         "--bind", "127.0.0.1", "--port", "0"],
                        stdout=log, stderr=log, start_new_session=sys.platform != "win32")
                    reader = None
                    stop = threading.Event()
                    threads, errors = [], []
                    def view(url):
                        try:
                            with urllib.request.urlopen(url, timeout=4) as response:
                                while not stop.is_set():
                                    if not response.read(4096):
                                        break
                        except Exception as error:
                            if not stop.is_set():
                                errors.append(str(error))
                    try:
                        deadline = time.perf_counter() + 15
                        while time.perf_counter() < deadline:
                            if service.poll() is not None:
                                log.flush()
                                log.seek(0)
                                raise RuntimeError("Synthetic service exited during startup:\n" + log.read())
                            try:
                                info = descriptor(path)
                                if info.get("ready"):
                                    break
                            except CameraStreamError:
                                pass
                            time.sleep(0.05)
                        else:
                            raise TimeoutError("Synthetic service did not start")
                        reader = SharedFrameReader(path)
                        for _ in range(viewer_count):
                            thread = threading.Thread(target=view, args=(
                                f"http://127.0.0.1:{info['http']['port']}/camera.mjpg",), daemon=True)
                            thread.start()
                            threads.append(thread)
                        # Warm up capture and active viewer encoding.
                        warmup = time.perf_counter() + 0.5
                        while time.perf_counter() < warmup:
                            reader.read()
                        samples = []
                        skipped = corrupt = 0
                        last = reader.sequence
                        deadline = time.perf_counter() + args.seconds
                        while time.perf_counter() < deadline:
                            frame = reader.read()
                            samples.append(reader.delivery_ms)
                            skipped += max(0, reader.sequence - last - 1)
                            last = reader.sequence
                            # Synthetic tag binds the pixels to the published sequence.
                            tag = int.from_bytes(frame.reshape(-1)[:8].tobytes(), "little")
                            corrupt += int(tag != reader.sequence)
                        percentiles = np.percentile(samples, [50, 95, 99, 100])
                        case = {"resolution": resolution, "viewers": viewer_count,
                                "n": len(samples), "median_ms": float(percentiles[0]),
                                "p95_ms": float(percentiles[1]), "p99_ms": float(percentiles[2]),
                                "max_ms": float(percentiles[3]), "skipped": skipped,
                                "integrity_errors": corrupt, "viewer_errors": list(errors)}
                        report["cases"].append(case)
                        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                        print(f"{resolution} viewers={viewer_count}: median {percentiles[0]:.3f}, "
                              f"p99 {percentiles[2]:.3f}, max {percentiles[3]:.3f} ms; "
                              f"skipped={skipped}, corrupt={corrupt}", flush=True)
                    finally:
                        stop.set()
                        if reader:
                            reader.release()
                        stop_owned(service, path)
                        for thread in threads:
                            thread.join(5)
    report["passed"] = all(c["p99_ms"] < 10 and not c["integrity_errors"] and not c["viewer_errors"]
                           for c in report["cases"])
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
