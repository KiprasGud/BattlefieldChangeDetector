"""Cross-flight frame pairing: which frame of flight B shows the same ground as each frame of flight A.

The flights differ in path, speed, altitude and camera angle, so timestamps say nothing: frame 10 of A may show
what frame 45 of B shows. Every A frame is compared with every B frame by content only:
1. retrieval: a VLAD vector (a global SIFT descriptor) per frame shortlists the TOP_K most similar B frames;
2. verification: the SIFT + MAGSAC registration used for image alignment must find a plausible homography whose
   footprints overlap by at least MIN_OVERLAP;
3. curation: the best B frame per A frame, taken greedily by match strength, skipping A frames that show ground
   an already chosen pair covers, capped at max_pairs.
"""
import logging
from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np

from ..alignment import Features, estimate_homography, extract_features

log = logging.getLogger(__name__)

MATCH_SIDE = 640            # working size for retrieval and verification (final alignment runs at full size)
MATCH_FEATURES = 1200
VLAD_WORDS = 64
VLAD_SAMPLE = 20_000        # descriptors used to train the per-batch codebook
TOP_K = 4                   # B candidates verified per A frame
EXHAUSTIVE_MAX = 64         # up to this many A x B combinations, verify them all and skip retrieval
MIN_OVERLAP = 0.5           # the two footprints must share at least half of the smaller one
REDUNDANT_OVERLAP = 0.5     # an A frame sharing this much ground with a chosen A frame adds nothing new
REDUNDANCY_NEIGHBOURS = 5   # A frames checked for redundancy: the most similar ones by VLAD, plus ...
SEQUENCE_NEIGHBOURS = 3     # ... the ones this close in the same flight
MAX_PAIRS = 20
SSIM_WINDOW = 11


@dataclass(eq=False)
class MatchedPair:
    a: int                  # frame index in flight A
    b: int                  # frame index in flight B
    inliers: int
    overlap: float          # footprint overlap, see footprint_overlap
    homography: np.ndarray  # B full-resolution pixels -> A full-resolution pixels
    ncc: float = 0.0        # zero-normalized cross-correlation after warping (registration quality)
    ssim: float = 0.0       # structural similarity of A and warped B over their overlap

    @property
    def score(self) -> float:
        return self.inliers * self.overlap


def describe(img: np.ndarray) -> Features:
    """Working-size SIFT features of one frame; its full-resolution pixels can be dropped afterwards."""
    return extract_features(img, MATCH_SIDE, MATCH_FEATURES)


# --- footprint geometry ---------------------------------------------------------------------------

def _rect(shape) -> np.ndarray:
    h, w = shape[:2]
    return np.float32([[0, 0], [w, 0], [w, h], [0, h]])


def _ccw(poly: np.ndarray) -> np.ndarray:
    """Same orientation for both polygons, as intersectConvexConvex expects."""
    x, y = poly[:, 0], poly[:, 1]
    return poly if float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) >= 0 else poly[::-1].copy()


def _covered(H: np.ndarray, src_shape, dst_shape) -> float:
    """Share of dst's area that src covers under the src->dst homography H."""
    pts = np.c_[_rect(src_shape), np.ones(4)] @ H.T
    if np.any(pts[:, 2] <= 1e-9):
        return 0.0  # part of src maps beyond the horizon: not a usable view
    proj = (pts[:, :2] / pts[:, 2:]).astype(np.float32)
    dst = _rect(dst_shape)
    area, _ = cv2.intersectConvexConvex(_ccw(proj), _ccw(dst))
    return float(area) / float(cv2.contourArea(dst))


def footprint_overlap(H, src_shape, dst_shape) -> float:
    """max(share of dst covered by src, share of src covered by dst): 1.0 when one view lies inside the other,
    so a low-altitude close-up of a high-altitude frame still counts as the same ground."""
    H = np.asarray(H, np.float64)
    try:
        H_inv = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        return 0.0
    return max(_covered(H, src_shape, dst_shape), _covered(H_inv, dst_shape, src_shape))


# --- retrieval (VLAD) -----------------------------------------------------------------------------

def _root_sift(des: np.ndarray) -> np.ndarray:
    des = des.astype(np.float32)
    return np.sqrt(des / (des.sum(axis=1, keepdims=True) + 1e-7))


def train_codebook(descriptor_sets, words: int = VLAD_WORDS, sample: int = VLAD_SAMPLE, seed: int = 0):
    """k-means visual words over RootSIFT descriptors sampled evenly from every frame; None if too few."""
    sets = [d for d in descriptor_sets if d is not None and len(d)]
    if not sets:
        return None
    rng = np.random.default_rng(seed)
    per_set = max(1, sample // len(sets))
    picked = [d if len(d) <= per_set else d[rng.choice(len(d), per_set, replace=False)] for d in sets]
    data = _root_sift(np.concatenate(picked))
    k = min(words, len(data) // 4)
    if k < 2:
        return None
    cv2.setRNGSeed(seed)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 15, 1e-4)
    _, _, centers = cv2.kmeans(data, k, None, criteria, 1, cv2.KMEANS_PP_CENTERS)
    return centers


def vlad(des: Optional[np.ndarray], centers: np.ndarray) -> np.ndarray:
    """Residuals to the nearest visual word, summed per word, intra- + power- + L2-normalized."""
    v = np.zeros(centers.shape, np.float32)
    if des is not None and len(des):
        x = _root_sift(des)
        d2 = (x * x).sum(axis=1, keepdims=True) - 2 * x @ centers.T + (centers * centers).sum(axis=1)
        nearest = d2.argmin(axis=1)
        np.add.at(v, nearest, x - centers[nearest])
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    v = v.ravel()
    v = np.sign(v) * np.sqrt(np.abs(v))
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _retrieve(feats_a, feats_b, top_k: int) -> tuple[list[list[int]], Optional[np.ndarray]]:
    """Candidate B frames per A frame, and A's VLAD vectors (None when every combination is verified)."""
    m, n = len(feats_a), len(feats_b)
    if m * n <= EXHAUSTIVE_MAX:
        return [list(range(n)) for _ in range(m)], None
    centers = train_codebook([f.descriptors for f in (*feats_a, *feats_b)])
    if centers is None:
        return [[] for _ in range(m)], None
    va = np.stack([vlad(f.descriptors, centers) for f in feats_a])
    vb = np.stack([vlad(f.descriptors, centers) for f in feats_b])
    k = min(top_k, n)
    return [np.argsort(-row, kind="stable")[:k].tolist() for row in va @ vb.T], va


# --- verification and scoring ---------------------------------------------------------------------

def _ssim_map(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Per-pixel SSIM (Wang et al. 2004) with an 11x11 Gaussian window, sigma 1.5."""
    x, y = x.astype(np.float32), y.astype(np.float32)

    def blur(img):
        return cv2.GaussianBlur(img, (SSIM_WINDOW, SSIM_WINDOW), 1.5)

    mx, my = blur(x), blur(y)
    sxx, syy, sxy = blur(x * x) - mx * mx, blur(y * y) - my * my, blur(x * y) - mx * my
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    return ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))


def structural_similarity(fa: Features, fb: Features, H: np.ndarray) -> float:
    """Mean SSIM of A and B warped into A, over their overlap, on the working-size CLAHE grayscale."""
    H_work = fa.to_work @ np.asarray(H, np.float64) @ np.linalg.inv(fb.to_work)
    h, w = fa.gray.shape[:2]
    warped = cv2.warpPerspective(fb.gray, H_work, (w, h))
    footprint = np.full(fb.gray.shape[:2], 255, np.uint8)
    valid = cv2.warpPerspective(footprint, H_work, (w, h), flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((SSIM_WINDOW, SSIM_WINDOW), np.uint8)) > 0  # windows must not see the border
    if valid.sum() < 100:
        return 0.0
    return float(_ssim_map(fa.gray, warped)[valid].mean())


def _verify(fa: Features, fb: Features, mirror: bool) -> Optional[MatchedPair]:
    reg = estimate_homography(None, None, src_features=fb, dst_features=fa, mirror=mirror)
    if reg is None:
        return None
    overlap = footprint_overlap(reg.H, fb.full_shape, fa.full_shape)
    if overlap < MIN_OVERLAP:
        return None
    return MatchedPair(a=-1, b=-1, inliers=reg.inliers, overlap=overlap, homography=reg.H, ncc=reg.ncc)


def _curate(best: list[MatchedPair], feats_a, va: Optional[np.ndarray], max_pairs: int) -> list[MatchedPair]:
    """Strongest matches first; an A frame showing mostly the same ground as a chosen one is skipped."""
    neighbours = None
    if va is not None:
        n = min(REDUNDANCY_NEIGHBOURS + 1, len(feats_a))
        neighbours = [set(np.argsort(-row, kind="stable")[:n].tolist()) for row in va @ va.T]
    seen: dict[tuple[int, int], bool] = {}

    def same_ground(i: int, k: int) -> bool:
        near = neighbours is None or abs(i - k) <= SEQUENCE_NEIGHBOURS or k in neighbours[i] or i in neighbours[k]
        if not near:
            return False
        key = (min(i, k), max(i, k))
        if key not in seen:
            fs, fd = feats_a[key[0]], feats_a[key[1]]
            reg = estimate_homography(None, None, src_features=fs, dst_features=fd, mirror=False)
            seen[key] = reg is not None and footprint_overlap(reg.H, fs.full_shape, fd.full_shape) >= REDUNDANT_OVERLAP
        return seen[key]

    chosen: list[MatchedPair] = []
    for pair in sorted(best, key=lambda p: p.score, reverse=True):
        if len(chosen) >= max_pairs:
            break
        if not any(same_ground(pair.a, c.a) for c in chosen):
            chosen.append(pair)
    return sorted(chosen, key=lambda p: p.a)


def match_flights(
    feats_a: Sequence[Features],
    feats_b: Sequence[Features],
    mirror: bool = False,
    max_pairs: int = MAX_PAIRS,
    top_k: int = TOP_K,
) -> list[MatchedPair]:
    """Curated (A frame, B frame) pairs that show the same ground, ordered by A frame.
    mirror=True also tries mirrored matches (only sensible for still images, never for video)."""
    candidates, va = _retrieve(feats_a, feats_b, top_k)
    best: dict[int, MatchedPair] = {}
    checked = 0
    for i, js in enumerate(candidates):
        for j in js:
            checked += 1
            found = _verify(feats_a[i], feats_b[j], mirror)
            if found is not None and (i not in best or found.score > best[i].score):
                found.a, found.b = i, int(j)
                best[i] = found
    chosen = _curate(list(best.values()), feats_a, va, max_pairs)
    for pair in chosen:
        pair.ssim = structural_similarity(feats_a[pair.a], feats_b[pair.b], pair.homography)
    log.info("Frame matching: %d x %d frames, %d candidates checked, %d A frames matched, %d pairs kept",
             len(feats_a), len(feats_b), checked, len(best), len(chosen))
    return chosen
