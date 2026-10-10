import cv2
import numpy as np
import os

from ..contracts import AlignResult


def normalize_brightness(img: np.ndarray) -> np.ndarray:
    """Normalize brightness/histogram to reduce shadow differences."""
    if len(img.shape) == 2:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(img)
    else:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl, a, b))
        return cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)


def write_debug_overlay(img_a: np.ndarray, aligned_b: np.ndarray, path: str = "debug_overlay.jpg"):
    """Debug helper that writes an A/B blend overlay."""
    blend = cv2.addWeighted(img_a, 0.5, aligned_b, 0.5, 0)
    cv2.imwrite(path, blend)


def get_downscale_factor(h, w, max_side=1600):
    if max(h, w) <= max_side:
        return 1.0
    return max_side / float(max(h, w))


def sanity_check_homography(H: np.ndarray) -> bool:
    if H is None or H.shape != (3, 3):
        return False
    det = np.linalg.det(H[:2, :2])
    if det <= 0:
        return False
    scale = np.sqrt(det)
    if not (0.5 <= scale <= 2.0):
        return False
    # small perspective terms
    if abs(H[2, 0]) > 0.005 or abs(H[2, 1]) > 0.005:
        return False
    return True


def align(img_a: np.ndarray, img_b: np.ndarray, debug: bool = False) -> AlignResult:
    """Warp img_b into img_a's frame using SIFT+RANSAC with ECC fallback."""
    if img_a.size == 0 or img_b.size == 0 or img_a.shape[0] == 0 or img_b.shape[0] == 0:
        return AlignResult(
            aligned_b=img_b, homography=None, quality=0.0, ok=False,
            **{"method": "none", "valid_mask": None}
        )

    h_a, w_a = img_a.shape[:2]
    h_b, w_b = img_b.shape[:2]

    scale_a = get_downscale_factor(h_a, w_a)
    scale_b = get_downscale_factor(h_b, w_b)

    img_a_small = cv2.resize(img_a, (int(w_a * scale_a), int(h_a * scale_a))) if scale_a < 1.0 else img_a
    img_b_small = cv2.resize(img_b, (int(w_b * scale_b), int(h_b * scale_b))) if scale_b < 1.0 else img_b

    img_a_norm = normalize_brightness(img_a_small)
    img_b_norm = normalize_brightness(img_b_small)

    gray_a = cv2.cvtColor(img_a_norm, cv2.COLOR_BGR2GRAY) if len(img_a_norm.shape) == 3 else img_a_norm
    gray_b = cv2.cvtColor(img_b_norm, cv2.COLOR_BGR2GRAY) if len(img_b_norm.shape) == 3 else img_b_norm

    sift = cv2.SIFT_create()
    kp_a, des_a = sift.detectAndCompute(gray_a, None)
    kp_b, des_b = sift.detectAndCompute(gray_b, None)

    homography = None
    quality = 0.0
    use_ecc = False
    method = "none"

    if des_a is not None and des_b is not None and len(kp_a) >= 4 and len(kp_b) >= 4:
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des_b, des_a, k=2)

        good_matches = []
        for m_n in matches:
            if len(m_n) == 2:
                m, n = m_n
                if m.distance < 0.75 * n.distance:
                    good_matches.append(m)
            elif len(m_n) == 1:
                good_matches.append(m_n[0])

        if len(good_matches) >= 4:
            src_pts = np.float32([kp_b[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
            dst_pts = np.float32([kp_a[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

            H_small, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
            if H_small is not None and mask is not None:
                inliers = np.sum(mask)
                inlier_ratio = inliers / len(good_matches) if len(good_matches) > 0 else 0.0
                
                if inliers >= 30 and inlier_ratio >= 0.3:
                    S_a = np.diag([1/scale_a, 1/scale_a, 1.0])
                    S_b = np.diag([scale_b, scale_b, 1.0])
                    H_full = S_a @ H_small @ S_b
                    H_full = H_full / H_full[2, 2]
                    
                    if sanity_check_homography(H_full):
                        homography = H_full
                        quality = inlier_ratio
                        method = "sift"
                    else:
                        use_ecc = True
                else:
                    use_ecc = True
            else:
                use_ecc = True
        else:
            use_ecc = True
    else:
        use_ecc = True

    if use_ecc or homography is None:
        gray_b_resized = cv2.resize(cv2.cvtColor(normalize_brightness(img_b), cv2.COLOR_BGR2GRAY) if len(img_b.shape) == 3 else normalize_brightness(img_b), (w_a, h_a))
        gray_a_full = cv2.cvtColor(normalize_brightness(img_a), cv2.COLOR_BGR2GRAY) if len(img_a.shape) == 3 else normalize_brightness(img_a)
        
        warp_matrix = np.eye(3, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-4)
        try:
            ecc_quality, warp_matrix = cv2.findTransformECC(gray_b_resized, gray_a_full, warp_matrix, cv2.MOTION_HOMOGRAPHY, criteria, None, 1)
            S_resize = np.diag([w_a / w_b, h_a / h_b, 1.0])
            H_full = warp_matrix @ S_resize
            H_full = H_full / H_full[2, 2]
            
            if sanity_check_homography(H_full):
                homography = H_full
                quality = ecc_quality
                method = "ecc"
            else:
                homography = None
                quality = 0.0
                method = "none"
        except Exception:
            homography = None
            quality = 0.0
            method = "none"

    if homography is not None:
        aligned_b = cv2.warpPerspective(img_b, homography, (w_a, h_a))
        
        white_mask = np.ones((h_b, w_b), dtype=np.uint8) * 255
        valid_mask = cv2.warpPerspective(white_mask, homography, (w_a, h_a))
        aligned_b = cv2.bitwise_and(aligned_b, aligned_b, mask=valid_mask)
        
        ok = True
        is_debug = debug or os.environ.get("DEBUG_ALIGN", "0") == "1"
        if is_debug:
            write_debug_overlay(img_a, aligned_b)
            
        return AlignResult(
            aligned_b=aligned_b, 
            homography=homography.tolist(), 
            quality=quality, 
            ok=ok,
            **{"method": method, "valid_mask": valid_mask}
        )
    else:
        resized = cv2.resize(img_b, (w_a, h_a))
        return AlignResult(
            aligned_b=resized, 
            homography=None, 
            quality=0.0, 
            ok=False,
            **{"method": "none", "valid_mask": None}
        )
