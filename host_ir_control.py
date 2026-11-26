"""WASD/gamepad control; press I to print downward IR and proximity readings."""
from host_velocity_client import main

if __name__ == '__main__':
    main(ir_hotkey='i')
