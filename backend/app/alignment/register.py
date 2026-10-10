"""Visual registration: find where image B lies in image A from pixel content alone.

Robust to resolution, aspect ratio, scale, rotation, mirroring and cropping: both images are matched at the
same working size with dense SIFT (mirror-aware) + MAGSAC, and the homography is checked in a
resolution-normalized frame. File metadata never enters: only decoded pixels are compared.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from ..contracts import AlignMethod, AlignResult

# Decode flags for every image read: pixels only, the EXIF orientation tag is ignored.
IMREAD_PIXELS = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION

WORK_SIDE = 1200            # both images are matched with this long side, so resolution differences vanish
MAX_UPSCALE = 4.0           # small images are enlarged at most this much for matching
SIFT_FEATURES = 6000
SIFT_CONTRAST = 0.005       # low threshold: flat terrain (grass, fields) must still yield keypoints
LOWE_RATIO = 0.75
MAGSAC_PX = 3.0             # reprojection threshold in working pixels
MIRROR_RETRY_INLIERS = 60   # a weaker direct match also tries horizontally mirrored B
MIN_INLIERS = 25
MIN_INLIER_RATIO = 0.15
MIN_NCC = 0.2               # visual agreement after warping; unrelated scenes measured 0.04-0.18
MIN_COVERAGE = 0.10         # share of A that B must overlap
ZOOM_RANGE = (0.2, 5.0)     # linear size of B's footprint in A, resolution-normalized
MAX_ANISOTROPY = 3.0
SNAP_TOL_PX = 0.5           # H this close to an exact flip / 90° turn + whole-pixel shift is snapped to it
FALLBACK_SIDE = 640
FALLBACK_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-4)
ECC_MIN_CC = 0.75           # identity-initialized ECC fallback must reach this correlation to count as aligned
HARMONIZE_MIN_ZOOM = 1.25


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


def _scale_matrix(sx: float, sy: float) -> np.ndarray:
    """Pixel-centre-correct scaling, the cv2.resize convention: x' = sx * x + (sx - 1) / 2."""
    return np.array([[sx, 0, 0.5 * (sx - 1)], [0, sy, 0.5 * (sy - 1)], [0, 0, 1]], np.float64)


def _resized(img: np.ndarray, side: int, max_scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Resize so the long side is `side`, enlarging at most `max_scale` times.
    Returns the image and the full -> resized pixel matrix."""
    h, w = img.shape[:2]
    s = min(side / max(h, w), max_scale)
    if s == 1:
        return img, np.eye(3)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    out = cv2.resize(img, size, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    return out, _scale_matrix(size[0] / w, size[1] / h)


def _gray(img: np.ndarray) -> np.ndarray:
    norm = normalize_brightness(img)
    return cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) if norm.ndim == 3 else norm


def _flip_matrix(width: int) -> np.ndarray:
    return np.array([[-1, 0, width - 1], [0, 1, 0], [0, 0, 1]], np.float64)


def _detect(gray: np.ndarray, n_features: int):
    # A new detector per call: OpenCV algorithm objects are not guaranteed thread-safe (jobs run in a pool).
    sift = cv2.SIFT_create(nfeatures=n_features, contrastThreshold=SIFT_CONTRAST)
    return sift.detectAndCompute(gray, None)


@dataclass
class Features:
    gray: np.ndarray                # CLAHE grayscale at working size
    keypoints: tuple
    descriptors: Optional[np.ndarray]
    to_work: np.ndarray             # 3x3: full-resolution pixels -> working pixels
    full_shape: tuple
    n_features: int = SIFT_FEATURES
    _mirror: Optional["Features"] = field(default=None, repr=False)

    def mirrored(self) -> "Features":
        """Features of the horizontally flipped image (SIFT descriptors are not mirror-invariant)."""
        if self._mirror is None:
            flipped = cv2.flip(self.gray, 1)
            kp, des = _detect(flipped, self.n_features)
            self._mirror = Features(flipped, kp, des, self.to_work, self.full_shape, self.n_features)
        return self._mirror


def extract_features(img: np.ndarray, side: int = WORK_SIDE, n_features: int = SIFT_FEATURES) -> Features:
    """SIFT features at a fixed working size. Smaller side/n_features trade precision for speed (recognition)."""
    small, to_work = _resized(img, side, MAX_UPSCALE)
    gray = _gray(small)
    kp, des = _detect(gray, n_features)
    return Features(gray, kp, des, to_work, img.shape[:2], n_features)


@dataclass
class Registration:
    H: np.ndarray           # 3x3, src pixels -> dst pixels at full resolution, mirroring included (det < 0)
    inliers: int
    inlier_ratio: float
    ncc: float              # zero-normalized cross-correlation after warping
    coverage: float         # share of dst covered by src
    mirrored: bool


def _project(H: np.ndarray, pts: np.ndarray) -> Optional[np.ndarray]:
    ph = H @ np.c_[pts, np.ones(len(pts))].T
    if np.any(ph[2] <= 1e-9):
        return None  # a point maps to infinity or behind the camera
    return (ph[:2] / ph[2]).T


def _corners(shape) -> np.ndarray:
    h, w = shape[:2]
    return np.float64([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])


def _area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _convex(poly: np.ndarray) -> bool:
    edges = np.roll(poly, -1, axis=0) - poly
    cross = edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1] - edges[:, 1] * np.roll(edges, -1, axis=0)[:, 0]
    return bool(np.all(cross > 0) or np.all(cross < 0))


def _plausible(H: np.ndarray, src_shape, dst_shape) -> bool:
    """Geometric sanity of a src->dst homography, independent of the two image resolutions."""
    if H is None or H.shape != (3, 3) or not np.all(np.isfinite(H)):
        return False
    proj = _project(H, _corners(src_shape))
    if proj is None or not _convex(proj):
        return False
    hs, ws = src_shape[:2]
    hd, wd = dst_shape[:2]
    src_area = max((ws - 1) * (hs - 1), 1) / max(hs, ws) ** 2  # same corner convention as proj
    dst_area = _area(proj) / max(hd, wd) ** 2
    zoom = np.sqrt(dst_area / src_area)
    if not ZOOM_RANGE[0] <= zoom <= ZOOM_RANGE[1]:
        return False
    # Local affine part at the image centre: reject extreme shearing / stretching.
    cx, cy = (ws - 1) / 2, (hs - 1) / 2
    w = H[2, 0] * cx + H[2, 1] * cy + H[2, 2]
    u = (H[0, 0] * cx + H[0, 1] * cy + H[0, 2]) / w
    v = (H[1, 0] * cx + H[1, 1] * cy + H[1, 2]) / w
    jac = np.array([[H[0, 0] - u * H[2, 0], H[0, 1] - u * H[2, 1]],
                    [H[1, 0] - v * H[2, 0], H[1, 1] - v * H[2, 1]]]) / w
    sv = np.linalg.svd(jac, compute_uv=False)
    return bool(sv[1] > 1e-9 and sv[0] / sv[1] <= MAX_ANISOTROPY)


def _match(src: Features, dst: Features) -> Optional[tuple[np.ndarray, int, int]]:
    """Working-size homography src -> dst, its inlier count and the number of ratio-test matches."""
    if src.descriptors is None or dst.descriptors is None or len(src.keypoints) < 4 or len(dst.keypoints) < 4:
        return None
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(src.descriptors, dst.descriptors, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < LOWE_RATIO * p[1].distance]
    if len(good) < 4:
        return None
    src_pts = np.float32([src.keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([dst.keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.USAC_MAGSAC, MAGSAC_PX, maxIters=10000, confidence=0.999)
    if H is None or mask is None:
        return None
    return H, int(mask.sum()), len(good)


def _overlap(dst_gray: np.ndarray, src_gray: np.ndarray, H_work: np.ndarray) -> tuple[float, float]:
    """(ZNCC of dst and warped src over their overlap, share of dst covered), at working size."""
    h, w = dst_gray.shape[:2]
    warped = cv2.warpPerspective(src_gray, H_work, (w, h))
    valid = cv2.warpPerspective(np.full(src_gray.shape[:2], 255, np.uint8), H_work, (w, h), flags=cv2.INTER_NEAREST) > 0
    coverage = float(valid.mean())
    if valid.sum() < 100:
        return 0.0, coverage
    a = dst_gray[valid].astype(np.float32)
    b = warped[valid].astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return (float((a * b).sum()) / denom if denom > 0 else 0.0), coverage


def _register(cand: Features, src: Features, dst: Features, mirrored: bool) -> Optional[Registration]:
    found = _match(cand, dst)
    if found is None:
        return None
    H_work, inliers, matches = found
    ratio = inliers / matches
    if inliers < MIN_INLIERS or ratio < MIN_INLIER_RATIO:
        return None
    if mirrored:
        H_work = H_work @ _flip_matrix(src.gray.shape[1])
    H = np.linalg.inv(dst.to_work) @ H_work @ src.to_work
    if abs(H[2, 2]) < 1e-12:
        return None
    H = H / H[2, 2]
    if not _plausible(H, src.full_shape, dst.full_shape):
        return None
    ncc, coverage = _overlap(dst.gray, src.gray, H_work)
    if ncc < MIN_NCC or coverage < MIN_COVERAGE:
        return None
    return Registration(H=H, inliers=inliers, inlier_ratio=ratio, ncc=ncc, coverage=coverage, mirrored=mirrored)


def estimate_homography(
    src: Optional[np.ndarray],
    dst: Optional[np.ndarray],
    src_features: Optional[Features] = None,
    dst_features: Optional[Features] = None,
    mirror: bool = True,
) -> Optional[Registration]:
    """Where does `src` appear inside `dst`? Returns the src->dst homography when the pictures show the same
    content (any resolution, aspect ratio, rotation, mirroring, crop), None otherwise.
    Pass precomputed features to skip extraction (e.g. cached reference images).
    mirror=False skips the mirrored retry (video frames are never mirrored; it would cost a second SIFT pass)."""
    fs = src_features if src_features is not None else extract_features(src)
    fd = dst_features if dst_features is not None else extract_features(dst)
    best = None
    for mirrored in (False, True) if mirror else (False,):
        reg = _register(fs.mirrored() if mirrored else fs, fs, fd, mirrored)
        if reg is not None and (best is None or reg.inliers > best.inliers):
            best = reg
        if best is not None and best.inliers >= MIRROR_RETRY_INLIERS:
            break
    return best


# The 8 ways to flip / turn a pixel grid by multiples of 90 degrees.
_GRID_TURNS = [np.array(m, np.float64) for m in (
    [[1, 0], [0, 1]], [[0, -1], [1, 0]], [[-1, 0], [0, -1]], [[0, 1], [-1, 0]],
    [[-1, 0], [0, 1]], [[1, 0], [0, -1]], [[0, 1], [1, 0]], [[0, -1], [-1, 0]],
)]


def _snap_to_pixel_grid(H: np.ndarray, src_shape) -> np.ndarray:
    """Exact flip / 90-degree turn + whole-pixel shift when H is within SNAP_TOL_PX of one (already-aligned pairs,
    crops, rotated or mirrored copies): the warp then copies pixels instead of blurring them by interpolation."""
    corners = _corners(src_shape)
    proj = _project(H, corners)
    if proj is None:
        return H
    for turn in _GRID_TURNS:
        moved = corners @ turn.T
        shift = np.round((proj - moved).mean(axis=0))
        if float(np.abs(moved + shift - proj).max()) < SNAP_TOL_PX:
            exact = np.eye(3)
            exact[:2, :2], exact[:2, 2] = turn, shift
            return exact
    return H


def _ecc_fallback(img_a: np.ndarray, img_b: np.ndarray) -> tuple[Optional[np.ndarray], float]:
    """Identity-initialized ECC on B resized to A's frame. Only rescues near-aligned, feature-poor pairs."""
    a_small, to_small = _resized(img_a, FALLBACK_SIDE)
    h, w = a_small.shape[:2]
    b_small = cv2.resize(img_b, (w, h), interpolation=cv2.INTER_AREA)
    b_to_small = _scale_matrix(w / img_b.shape[1], h / img_b.shape[0])
    try:
        cc, W = cv2.findTransformECC(
            _gray(b_small), _gray(a_small), np.eye(3, dtype=np.float32), cv2.MOTION_HOMOGRAPHY, FALLBACK_CRITERIA, None, 3,
        )
    except cv2.error:
        return None, 0.0
    # W maps the resized B onto A (template = B).
    H = np.linalg.inv(to_small) @ W.astype(np.float64) @ b_to_small
    H = H / H[2, 2]
    if cc < ECC_MIN_CC or not _plausible(H, img_b.shape, img_a.shape):
        return None, 0.0
    return H, float(cc)


def harmonize_resolution(img_a: np.ndarray, homography, b_shape, min_zoom: float = HARMONIZE_MIN_ZOOM) -> np.ndarray:
    """Blur A down to B's ground resolution when B is coarser, so a pixel diff compares like with like.
    Returns img_a itself (no copy) when B is about as sharp as A or there is no homography."""
    if homography is None:
        return img_a
    proj = _project(np.asarray(homography, np.float64), _corners(b_shape))
    if proj is None:
        return img_a
    hb, wb = b_shape[:2]
    zoom = np.sqrt(_area(proj) / max((wb - 1) * (hb - 1), 1))  # A pixels per B pixel, linear
    if not np.isfinite(zoom) or zoom < min_zoom:
        return img_a
    h, w = img_a.shape[:2]
    small = cv2.resize(img_a, (max(1, round(w / zoom)), max(1, round(h / zoom))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def warp_into(a_shape, img_b: np.ndarray, homography) -> tuple[np.ndarray, np.ndarray]:
    """img_b warped into A's frame by the B->A homography (black outside B's footprint), and that footprint mask."""
    h_a, w_a = a_shape[:2]
    homography = np.asarray(homography, np.float64)
    aligned_b = cv2.warpPerspective(img_b, homography, (w_a, h_a))
    white_mask = np.ones(img_b.shape[:2], dtype=np.uint8) * 255
    valid_mask = cv2.warpPerspective(white_mask, homography, (w_a, h_a))
    return cv2.bitwise_and(aligned_b, aligned_b, mask=valid_mask), valid_mask


def align(img_a: np.ndarray, img_b: np.ndarray, debug: bool = False) -> AlignResult:
    """Warp img_b into img_a's frame: mirror-aware SIFT + MAGSAC (sub-pixel), ECC fallback for feature-poor pairs."""
    if img_a.size == 0 or img_b.size == 0:
        return AlignResult(aligned_b=img_b, homography=None, quality=0.0, ok=False, method="none", valid_mask=None)

    h_a, w_a = img_a.shape[:2]
    method: AlignMethod
    reg = estimate_homography(img_b, img_a)
    if reg is not None:
        method, quality = "sift", reg.ncc
        homography = _snap_to_pixel_grid(reg.H, img_b.shape)
    else:
        homography, quality = _ecc_fallback(img_a, img_b)
        method = "ecc"

    if homography is None:
        resized = cv2.resize(img_b, (w_a, h_a))
        return AlignResult(
            aligned_b=resized,
            homography=None,
            quality=0.0,
            ok=False,
            method="none",
            valid_mask=None,
        )

    aligned_b, valid_mask = warp_into(img_a.shape, img_b, homography)

    if debug or os.environ.get("DEBUG_ALIGN", "0") == "1":
        write_debug_overlay(img_a, aligned_b)

    return AlignResult(
        aligned_b=aligned_b,
        homography=homography.tolist(),
        quality=float(np.clip(quality, 0.0, 1.0)),
        ok=True,
        method=method,
        valid_mask=valid_mask,
    )
