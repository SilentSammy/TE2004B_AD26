import time


CLOCK_CORRECTION_MS = -674


while True:
    unix_ms = time.time_ns() // 1_000_000 + CLOCK_CORRECTION_MS
    print("%04d" % (unix_ms % 10_000))
    time.sleep_ms(100)