"""Find the best blue circular HSV candidate; thresholds are OpenCV HSV."""
from pathlib import Path

import cv2
import numpy as np


class BallDetector:
    def __init__(self):
        lower, upper = (100, 100, 35), (130, 255, 255)
        try:
            lines = Path(__file__).with_name("ball_thresholds.txt").read_text().splitlines()
            values = [tuple(map(int, line.split(","))) for line in lines[:2]]
            if len(values) != 2 or any(len(row) != 3 for row in values):
                raise ValueError("expected two HSV triples")
            if any(not 0 <= a <= b <= limit for a, b, limit in zip(*values, (179, 255, 255))):
                raise ValueError("invalid HSV range")
            lower, upper = values
        except (OSError, UnicodeError, ValueError):
            pass
        self.lower, self.upper = np.array(lower, np.uint8), np.array(upper, np.uint8)

    def detect(self, frame):
        hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (11, 11), 0), cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.lower, self.upper)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best, score = None, 0
        for contour in contours:
            area, perimeter = cv2.contourArea(contour), cv2.arcLength(contour, True)
            if area < 100 or perimeter == 0 or cv2.minEnclosingCircle(contour)[1] < 10:
                continue
            circularity = 4 * np.pi * area / perimeter ** 2
            moments = cv2.moments(contour)
            if circularity > score and moments["m00"]:
                best = (contour, (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]))
                score = circularity
        return [] if best is None else [best]
