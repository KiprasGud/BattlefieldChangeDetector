"""Detection metrics: greedy one-to-one matching of predicted and ground-truth boxes by IoU."""

IOU_MATCH = 0.3  # loose on purpose: LLM boxes are coarse, we care whether the right object was found


def iou(a, b) -> float:
    iy = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    ix = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iy * ix
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(pred: list, truth: list, threshold: float = IOU_MATCH) -> dict:
    """pred/truth: lists of [ymin, xmin, ymax, xmax]. Returns tp/fp/fn and IoUs of matched pairs."""
    pairs = sorted(
        ((iou(p, t), i, j) for i, p in enumerate(pred) for j, t in enumerate(truth)),
        reverse=True,
    )
    used_p, used_t, ious = set(), set(), []
    for score, i, j in pairs:
        if score < threshold:
            break
        if i in used_p or j in used_t:
            continue
        used_p.add(i)
        used_t.add(j)
        ious.append(score)
    return {"tp": len(ious), "fp": len(pred) - len(ious), "fn": len(truth) - len(ious), "ious": ious}


def summarize(counts: list[dict]) -> dict:
    tp = sum(c["tp"] for c in counts)
    fp = sum(c["fp"] for c in counts)
    fn = sum(c["fn"] for c in counts)
    ious = [x for c in counts for x in c["ious"]]
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "mean_iou": sum(ious) / len(ious) if ious else 0.0,
    }
