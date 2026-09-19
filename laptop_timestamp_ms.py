import time


while True:
    unix_ms = time.time_ns() // 1_000_000
    print(f"{unix_ms % 10_000:04d}", flush=True)
    time.sleep(0.1)