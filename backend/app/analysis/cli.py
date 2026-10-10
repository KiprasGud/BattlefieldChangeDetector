"""Manual test: python -m app.analysis.cli a.jpg b.jpg "criteria" [--lang lt]  (run from backend/)."""
import argparse

import cv2
from dotenv import load_dotenv

from . import analyze


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("image_a")
    p.add_argument("image_b")
    p.add_argument("criteria")
    p.add_argument("--lang", default="en")
    args = p.parse_args()

    a, b = cv2.imread(args.image_a), cv2.imread(args.image_b)
    if a is None or b is None:
        raise SystemExit("Could not read one of the images")
    print(analyze(a, b, args.criteria, args.lang).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
