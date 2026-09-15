"""Conservative single-glyph crop for gold bid text; never returns a value."""
import cv2


def compact_bid_glyph(crop):
    if crop is None or crop.size == 0:
        return None
    height, width = crop.shape[:2]
    mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), (15, 80, 140), (45, 255, 255))
    points = cv2.findNonZero(mask)
    if points is None:
        return None
    x, y, w, h = cv2.boundingRect(points)
    # Reject edge/background fragments and wide amounts. Keep every colored
    # pixel; do not select one component out of a multi-digit amount.
    if not (.25*height <= h <= .85*height and w <= .25*width
            and .30*width <= x+w/2 <= .70*width
            and x >= 3 and y >= 3 and x+w+3 <= width and y+h+3 <= height):
        return None
    return crop[y-3:y+h+3, x-3:x+w+3]
