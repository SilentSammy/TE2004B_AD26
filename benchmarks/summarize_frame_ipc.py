"""Render frame_ipc.py JSON reports as a Markdown comparison and per-case CSV."""

import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in args.reports]
    lines = ["# Synthetic frame IPC comparison", "",
             "All times are milliseconds. p99 values are per-case estimates from short runs, "
             "not worst-case guarantees. Delivery ends after the raw receiver's private copy.", "",
             "The occupied desktop ran at nice 19 with a one-core CPU quota, low cgroup CPU "
             "weight and a 512 MiB memory limit. The laptop used below-normal priority. "
             "These are intentionally different safety constraints, not an equal-priority hardware comparison.", "",
             "## Environment", "",
             "| Report | OS | Python | NumPy / OpenCV | Logical CPUs | Priority |",
             "| --- | --- | --- | --- | ---: | --- |"]
    for name, report in reports:
        lines.append(f"| {name} | {report['platform']} | {report['python']} | "
                     f"{report['numpy']} / {report['opencv']} | {report['cpu_count']} | {report['priority']} |")
    lines += ["", "## Delivery across all five patterns", "",
              "Worst p99 and maximum are the largest per-case values at that resolution/mode. "
              "CPU is a percentage of one core, including generation, CRC and codec work.", "",
              "| Report | Resolution | Mode | Median range | Worst p95 | Worst p99 | Maximum | Min publisher FPS | CPU range |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    rows = []
    for name, report in reports:
        cases = report["cases"]
        for resolution in dict.fromkeys(c["resolution"] for c in cases):
            for mode in dict.fromkeys(c["mode"] for c in cases):
                group = [c for c in cases if c["resolution"] == resolution and c["mode"] == mode]
                if not group:
                    continue
                timings = [c["consumers"]["raw"]["delivery_ms"] for c in group]
                lines.append(
                    f"| {name} | {resolution} | {mode} | "
                    f"{min(t['median'] for t in timings):.3f}–{max(t['median'] for t in timings):.3f} | "
                    f"{max(t['p95'] for t in timings):.3f} | {max(t['p99'] for t in timings):.3f} | "
                    f"{max(t['max'] for t in timings):.3f} | "
                    f"{min(c['effective_publisher_fps'] for c in group):.1f} | "
                    f"{min(c['cpu_one_core_percent'] for c in group):.1f}–{max(c['cpu_one_core_percent'] for c in group):.1f}% |")
        for case in cases:
            raw = case["consumers"]["raw"]
            jpeg = case["consumers"].get("jpeg")
            timing = raw["delivery_ms"]
            rows.append({
                "report": name, "resolution": case["resolution"], "pattern": case["pattern"],
                "mode": case["mode"], "published": case["published"], "received": raw["received"],
                "skipped": raw["skipped"], "integrity_errors": raw["integrity_errors"],
                "order_errors": raw["order_errors"],
                **{f"delivery_{k}_ms": timing[k] for k in ["median", "p95", "p99", "max"]},
                "publisher_fps": case["effective_publisher_fps"],
                "publisher_late_slots": case["publisher_late_slots"],
                "cpu_one_core_percent": case["cpu_one_core_percent"],
                "host_busy_percent": case["host_busy_percent"],
                "jpeg_encode_median_ms": jpeg["jpeg_encode_ms"]["median"] if jpeg else None,
                "jpeg_decode_median_ms": jpeg["jpeg_decode_ms"]["median"] if jpeg else None,
                "jpeg_median_bytes": jpeg["jpeg_bytes"]["median"] if jpeg else None,
                "jpeg_received": jpeg["received"] if jpeg else None,
                "jpeg_skipped": jpeg["skipped"] if jpeg else None,
            })
    lines += ["", "## 1080p image complexity and JPEG work", "",
              "Encode and decode are measured separately in the extra worker. Its effective "
              "FPS can fall while the independent raw receiver tracks publication. "
              "The one-core cap also slowed the desktop publisher to 25.7 FPS in the "
              "1080p white-noise case; zero raw skips does not imply 30 FPS in that case.", "",
              "| Report | Pattern | Encode median | Decode median | JPEG KiB | Codec FPS | Raw p99 |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, report in reports:
        for case in report["cases"]:
            if case["resolution"] == "1920x1080" and case["mode"] == "with_jpeg":
                j = case["consumers"]["jpeg"]
                lines.append(f"| {name} | {case['pattern']} | {j['jpeg_encode_ms']['median']:.2f} | "
                             f"{j['jpeg_decode_ms']['median']:.2f} | {j['jpeg_bytes']['median'] / 1024:.1f} | "
                             f"{j['received'] / case['duration_seconds']:.1f} | "
                             f"{case['consumers']['raw']['delivery_ms']['p99']:.3f} |")
    lines += ["", "## Integrity and target checks", ""]
    for name, report in reports:
        errors = sum(c["integrity_errors"] + c["order_errors"]
                     for case in report["cases"] for c in case["consumers"].values())
        missed = [f"{c['resolution']} {c['pattern']} {c['mode']}"
                  for c in report["cases"] if c["consumers"]["raw"]["delivery_ms"]["p99"] >= 10]
        lines += [f"- **{name}**: {len(report['cases'])} cases; {errors} integrity/order errors; "
                  f"{sum(c['consumers']['raw']['received'] for c in report['cases'])} raw snapshots; "
                  f"{sum(c['consumers']['raw']['skipped'] for c in report['cases'])} raw skipped frames; "
                  f"{len(missed)} cases with raw p99 ≥10 ms."]
        if missed:
            lines += ["  Cases: " + "; ".join(missed) + "."]
        if report.get("error"):
            lines += ["  Run stopped with an error; see the source JSON."]
    lines += ["", "## Limits", "",
              "- No camera, network transport, browser, marker detector, or pose telemetry was benchmarked.",
              "- Low-priority scheduling, live desktop load and its CPU quota can affect latency tails.",
              "- The CRC instrumentation adds CPU/memory traffic even though verification is outside delivery timing.",
              "- Codec workers do encode plus decode; an actual server normally only encodes.",
              "- The benchmark uses related spawn processes; independent-service discovery and shared-memory lifetime still need testing.",
              "- Observing the production PID and host load does not establish an unchanged application FPS.", ""]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(args.output)
    print(args.output.with_suffix(".csv"))


if __name__ == "__main__":
    main()
