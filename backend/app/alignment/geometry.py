import numpy as np
from typing import List

def get_tiles(img: np.ndarray, rows: int = 4, cols: int = 4, overlap: float = 0.2):
    """
    Splits image into rows x cols tiles with overlap.
    Returns list of dicts: {'image': tile_img, 'y': start_y, 'x': start_x, 'h': tile_h, 'w': tile_w}
    """
    h, w = img.shape[:2]
    step_y = int(h / (rows - overlap * (rows - 1)))
    step_x = int(w / (cols - overlap * (cols - 1)))
    
    tile_h = int(step_y * (1 + overlap))
    tile_w = int(step_x * (1 + overlap))
    
    tiles = []
    for r in range(rows):
        for c in range(cols):
            y = int(r * step_y * (1 - overlap))
            x = int(c * step_x * (1 - overlap))
            
            # bounds check
            y = min(y, h - tile_h) if h > tile_h else 0
            x = min(x, w - tile_w) if w > tile_w else 0
            
            y_end = min(y + tile_h, h)
            x_end = min(x + tile_w, w)
            
            tiles.append({
                'image': img[y:y_end, x:x_end],
                'y': y,
                'x': x,
                'h': y_end - y,
                'w': x_end - x
            })
    return tiles

def map_box_to_full(box_1000: List[int], tile: dict, full_h: int, full_w: int) -> List[int]:
    """
    Maps a [ymin, xmin, ymax, xmax] box from 0-1000 scale in the tile 
    back to a 0-1000 scale in the full image.
    """
    ymin, xmin, ymax, xmax = box_1000
    
    # tile pixel coords
    py_min = (ymin / 1000.0) * tile['h'] + tile['y']
    px_min = (xmin / 1000.0) * tile['w'] + tile['x']
    py_max = (ymax / 1000.0) * tile['h'] + tile['y']
    px_max = (xmax / 1000.0) * tile['w'] + tile['x']
    
    # full 1000 coords
    return [
        int(py_min / full_h * 1000),
        int(px_min / full_w * 1000),
        int(py_max / full_h * 1000),
        int(px_max / full_w * 1000)
    ]

def non_max_suppression(boxes_1000: List[List[int]], iou_threshold: float = 0.3) -> List[List[int]]:
    """Simple NMS for 0-1000 scale boxes."""
    if not boxes_1000:
        return []
        
    b = np.array(boxes_1000, dtype=np.float32)
    y1, x1, y2, x2 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    areas = (y2 - y1) * (x2 - x1)
    
    # Assume we process them in arbitrary order (or they should be sorted by confidence)
    order = np.argsort(areas)[::-1] # large to small
    keep = []
    
    while order.size > 0:
        i = order[0]
        keep.append(boxes_1000[i])
        
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        
        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]
        
    return keep
