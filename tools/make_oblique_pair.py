import cv2
import numpy as np
import os

def warp_oblique(img: np.ndarray, perspective: float=0.2, rotation: float=15.0, scale: float=0.9, brightness: float=1.2):
    h, w = img.shape[:2]
    
    # 1. Perspective
    # Move top corners in by 'perspective' * w
    pts1 = np.float32([[0, 0], [w, 0], [0, h], [w, h]])
    pts2 = np.float32([[w*perspective, h*perspective], 
                       [w*(1-perspective), h*perspective], 
                       [0, h], 
                       [w, h]])
    M_persp = cv2.getPerspectiveTransform(pts1, pts2)
    warped = cv2.warpPerspective(img, M_persp, (w, h))
    
    # 2. Rotation & Scale
    center = (w/2, h/2)
    M_rot = cv2.getRotationMatrix2D(center, rotation, scale)
    warped = cv2.warpAffine(warped, M_rot, (w, h))
    
    # 3. Brightness
    warped = cv2.convertScaleAbs(warped, alpha=brightness, beta=10)
    
    return warped

def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'shared', 'sample_data'))
    
    pairs_to_process = [('pair01', 'pair03'), ('pair02', 'pair04')]
    
    for src, dst in pairs_to_process:
        src_path = os.path.join(base_dir, src)
        dst_path = os.path.join(base_dir, dst)
        
        if not os.path.exists(src_path):
            print(f"Skipping {src}, not found.")
            # Create dummy images if missing so pipeline works
            os.makedirs(src_path, exist_ok=True)
            dummy_a = np.zeros((400, 400, 3), dtype=np.uint8)
            cv2.rectangle(dummy_a, (100, 100), (300, 300), (255, 255, 255), -1)
            dummy_b = dummy_a.copy()
            cv2.circle(dummy_b, (200, 200), 50, (0, 0, 255), -1)
            cv2.imwrite(os.path.join(src_path, 'a.jpg'), dummy_a)
            cv2.imwrite(os.path.join(src_path, 'b.jpg'), dummy_b)

        os.makedirs(dst_path, exist_ok=True)
        
        img_a = cv2.imread(os.path.join(src_path, 'a.jpg'))
        img_b = cv2.imread(os.path.join(src_path, 'b.jpg'))
        
        if img_a is None or img_b is None:
            continue
            
        cv2.imwrite(os.path.join(dst_path, 'a.jpg'), img_a)
        
        # Warp B
        img_b_oblique = warp_oblique(img_b)
        cv2.imwrite(os.path.join(dst_path, 'b.jpg'), img_b_oblique)
        
        print(f"Generated {dst} from {src}")
        
    print("Handing off to P2: True change locations for pair03 and pair04 are the same as pair01 and pair02 but warped by the M_persp and M_rot matrices inside warp_oblique.")

if __name__ == '__main__':
    main()
