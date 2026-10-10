import cv2
import numpy as np
from typing import List

def change_heatmap(img_a: np.ndarray, aligned_b: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """
    Produces a float32 [0, 1] change heatmap based on Lab colour difference and gradient difference.
    Suppresses shadows (pure luminance drops).
    Applies morphological cleanup, Gaussian blur, and sets masked area to 0.
    """
    if img_a.size == 0 or aligned_b.size == 0 or img_a.shape != aligned_b.shape:
        return np.zeros(img_a.shape[:2], dtype=np.float32)

    lab_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab_b = cv2.cvtColor(aligned_b, cv2.COLOR_BGR2LAB).astype(np.float32)

    dL = lab_b[:, :, 0] - lab_a[:, :, 0]
    da = lab_b[:, :, 1] - lab_a[:, :, 1]
    db = lab_b[:, :, 2] - lab_a[:, :, 2]

    # Shadow suppression: if dL < 0, weight it less
    dL_suppressed = np.where(dL < 0, dL * 0.2, dL)
    
    lab_diff = np.sqrt(dL_suppressed**2 + da**2 + db**2)

    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(aligned_b, cv2.COLOR_BGR2GRAY)
    
    grad_x_a = cv2.Sobel(gray_a, cv2.CV_32F, 1, 0, ksize=3)
    grad_y_a = cv2.Sobel(gray_a, cv2.CV_32F, 0, 1, ksize=3)
    grad_x_b = cv2.Sobel(gray_b, cv2.CV_32F, 1, 0, ksize=3)
    grad_y_b = cv2.Sobel(gray_b, cv2.CV_32F, 0, 1, ksize=3)
    
    grad_diff = np.sqrt((grad_x_b - grad_x_a)**2 + (grad_y_b - grad_y_a)**2)

    combined = lab_diff + 0.5 * grad_diff
    combined = np.clip(combined / 100.0, 0, 1)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)

    blurred = cv2.GaussianBlur(cleaned, (15, 15), 0)

    if valid_mask is not None:
        blurred[valid_mask == 0] = 0.0

    return blurred.astype(np.float32)


def candidate_boxes(heatmap: np.ndarray, top_n: int = 10) -> List[List[int]]:
    """
    Extracts top_n candidate bounding boxes from the heatmap.
    Returns list of [ymin, xmin, ymax, xmax] mapped to 0-1000 scale.
    """
    if heatmap.size == 0:
        return []

    h, w = heatmap.shape

    thresh_val = 0.2
    _, binary = cv2.threshold(heatmap, thresh_val, 1.0, cv2.THRESH_BINARY)
    binary = (binary * 255).astype(np.uint8)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    candidates = []
    for i in range(1, num_labels):
        x, y, bw, bh, area = stats[i]
        
        comp_mask = (labels == i)
        score = np.mean(heatmap[comp_mask]) * area
        
        xmin = int(x / w * 1000)
        ymin = int(y / h * 1000)
        xmax = int((x + bw) / w * 1000)
        ymax = int((y + bh) / h * 1000)
        
        candidates.append((score, [ymin, xmin, ymax, xmax]))

    candidates.sort(key=lambda c: c[0], reverse=True)
    return [c[1] for c in candidates[:top_n]]
