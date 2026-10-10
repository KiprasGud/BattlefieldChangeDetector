import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import cv2
import numpy as np

from app.diff.heatmap import change_heatmap, candidate_boxes

def test_identical_images():
    img_a = np.ones((200, 200, 3), dtype=np.uint8) * 128
    img_b = img_a.copy()
    valid_mask = np.ones((200, 200), dtype=np.uint8) * 255
    
    hm = change_heatmap(img_a, img_b, valid_mask)
    boxes = candidate_boxes(hm)
    
    assert len(boxes) == 0

def test_drawn_circle_found():
    img_a = np.zeros((200, 200, 3), dtype=np.uint8)
    img_b = img_a.copy()
    
    # Draw a circle in B
    cv2.circle(img_b, (100, 100), 20, (255, 255, 255), -1)
    
    valid_mask = np.ones((200, 200), dtype=np.uint8) * 255
    
    hm = change_heatmap(img_a, img_b, valid_mask)
    boxes = candidate_boxes(hm)
    
    assert len(boxes) > 0
    ymin, xmin, ymax, xmax = boxes[0]
    
    assert 300 < ymin < 500
    assert 300 < xmin < 500
    assert 500 < ymax < 700
    assert 500 < xmax < 700
