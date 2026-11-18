"""Installed on the Zumo only. Hold button A during boot to enter the REPL."""
from zumo_2040_robot import robot
robot.Motors().off()
if robot.ButtonA().is_pressed():
    print('Hardware server bypassed: button A held')
else:
    import hardware_server
    hardware_server.main()
