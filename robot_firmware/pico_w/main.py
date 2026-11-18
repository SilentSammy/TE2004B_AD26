"""Safe Pico W starter: hardware available at the REPL; motors stay stopped."""
from zumo_client import Zumo
import time
car = Zumo()
for attempt in range(20):
    try:
        print('Zumo hardware connected:', car.info())
        car.stop()
        break
    except OSError as error:
        if attempt == 19:
            print('Zumo UART unavailable:', error)
        time.sleep_ms(100)
# Add your Wi-Fi, navigation and sensor-fusion application here.
# Main exits to the USB REPL; no motor command is issued automatically.
