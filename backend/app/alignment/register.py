"""PERSON 1 owns this file. Replace the stub with ORB/SIFT + RANSAC homography (+ ECC fallback)."""
import cv2
import numpy as np

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


def align(img_a: np.ndarray, img_b: np.ndarray, debug: bool = False) -> AlignResult:
    """Warp img_b into img_a's frame using SIFT+RANSAC with ECC fallback."""
    h, w = img_a.shape[:2]

    img_a_norm = normalize_brightness(img_a)
    img_b_norm = normalize_brightness(img_b)

    gray_a = cv2.cvtColor(img_a_norm, cv2.COLOR_BGR2GRAY) if len(img_a_norm.shape) == 3 else img_a_norm
    gray_b = cv2.cvtColor(img_b_norm, cv2.COLOR_BGR2GRAY) if len(img_b_norm.shape) == 3 else img_b_norm

    sift = cv2.SIFT_create()
    kp_a, des_a = sift.detectAndCompute(gray_a, None)
    kp_b, des_b = sift.detectAndCompute(gray_b, None)

    homography = None
    quality = 0.0
    use_ecc = False

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

            homography, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
            if mask is not None:
                inliers = np.sum(mask)
                quality = inliers / len(good_matches) if len(good_matches) > 0 else 0.0
            else:
                use_ecc = True
        else:
            use_ecc = True
    else:
        use_ecc = True

    if use_ecc or homography is None or quality < 0.1:
        # Fallback: ECC if too few matches or RANSAC quality was poor
        warp_matrix = np.eye(3, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-4)
        try:
            _, warp_matrix = cv2.findTransformECC(gray_b, gray_a, warp_matrix, cv2.MOTION_HOMOGRAPHY, criteria, None, 1)
            homography = warp_matrix
            quality = 0.5  # ECC converged
        except cv2.error:
            if homography is None:
                homography = None
                quality = 0.0

    if homography is not None:
        aligned_b = cv2.warpPerspective(img_b, homography, (w, h))
        
        white_mask = np.ones((img_b.shape[0], img_b.shape[1]), dtype=np.uint8) * 255
        warped_mask = cv2.warpPerspective(white_mask, homography, (w, h))
        aligned_b = cv2.bitwise_and(aligned_b, aligned_b, mask=warped_mask)
        
        ok = quality >= 0.1
        if debug:
            write_debug_overlay(img_a, aligned_b)
            
        return AlignResult(
            aligned_b=aligned_b, 
            homography=homography.tolist(), 
            quality=quality, 
            ok=ok
        )
    else:
        resized = cv2.resize(img_b, (w, h))
        return AlignResult(aligned_b=resized, homography=None, quality=0.0, ok=False)
