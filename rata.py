#!/usr/bin/env python3
"""
rata.py - klipper ut ett papper (teckning, vykort) ur ett foto och rätar ut det
till en rektangel med räta vinklar. Ingen AI: kantdetektering + perspektivtransform.

Användning:
    python3 rata.py foto.jpg                 # automatiskt, sparar foto_rak.jpg
    python3 rata.py *.jpg --pdf              # flera bilder + A4-PDF (bilden på vänstra halvan)
    python3 rata.py *.jpg --dubbel           # A4-PDF med bilden på båda halvorna (klipp itu)
    python3 rata.py foto.jpg --edit          # visa hörnen, dra dem rätt, Enter = spara
    python3 rata.py foto.jpg --ratio auto    # behåll papperets uppmätta proportioner

Installation (en gång):
    pip3 install opencv-python pillow numpy
    pip3 install pillow-heif                 # bara om du har .HEIC-bilder
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

DPI = 300
HALF_A4_MM = (148.5, 210.0)          # bredd, höjd (stående)
A4_LANDSCAPE_MM = (297.0, 210.0)


def mm_to_px(mm):
    return int(round(mm / 25.4 * DPI))


def load(path):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def order(pts):
    """Sortera hörn: övre vänster, övre höger, nedre höger, nedre vänster."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]],
                    dtype=np.float32)


def find_corners(img):
    """Hitta det ljusa, ofärgade pappret som täcker bildens mitt och anpassa en fyrhörning."""
    h, w = img.shape[:2]
    scale = 1000 / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]

    hsv = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]
    # Papper = ljust och nästan ofärgat. Tröskeln för ljushet sätts adaptivt (Otsu).
    t, _ = cv2.threshold(val, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    paper = ((val > t) & (sat < 60)).astype(np.uint8) * 255
    # Fyll i teckningen så att pappret blir en sammanhängande yta.
    paper = cv2.morphologyEx(paper, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    paper = cv2.morphologyEx(paper, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

    contours, _ = cv2.findContours(paper, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    center = (sw / 2, sh / 2)
    inside = [c for c in contours if cv2.pointPolygonTest(c, center, False) >= 0]
    c = max(inside or contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.1 * sw * sh:
        return None

    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    quad = None
    for eps in np.linspace(0.01, 0.1, 19):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            quad = approx
            break
    if quad is None:
        quad = cv2.boxPoints(cv2.minAreaRect(hull))
    rough = order(np.asarray(quad, dtype=np.float32).reshape(4, 2))
    # Förfina: anpassa en rak linje per sida med RANSAC, så att saker som sticker ut
    # (en hand, något vitt bredvid pappret) inte drar hörnen fel.
    refined = refine_sides(c.reshape(-1, 2).astype(np.float32), rough, band=0.06 * max(sw, sh))
    return (refined if refined is not None else rough) / scale


def refine_sides(points, quad, band, iters=400, tol=2.0):
    rng = np.random.default_rng(0)
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        d = b - a
        length = np.linalg.norm(d)
        n = np.array([-d[1], d[0]]) / length
        dist = np.abs((points - a) @ n)
        t = (points - a) @ d / length ** 2
        cand = points[(dist < band) & (t > -0.05) & (t < 1.05)]
        if len(cand) < 20:
            return None
        best, best_count = None, 0
        for _ in range(iters):
            p, q = cand[rng.choice(len(cand), 2, replace=False)]
            v = q - p
            if np.linalg.norm(v) < 0.2 * length:
                continue
            nn = np.array([-v[1], v[0]]) / np.linalg.norm(v)
            inl = np.abs((cand - p) @ nn) < tol
            if inl.sum() > best_count:
                best, best_count = inl, inl.sum()
        if best is None:
            return None
        vx, vy, x0, y0 = cv2.fitLine(cand[best], cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    corners = []
    for i in range(4):  # hörn i = skärning mellan sida i-1 och sida i
        (p1, v1), (p2, v2) = lines[i - 1], lines[i]
        m = np.array([v1, -v2]).T
        if abs(np.linalg.det(m)) < 1e-6:
            return None
        s = np.linalg.solve(m, p2 - p1)[0]
        corners.append(p1 + s * v1)
    return order(np.array(corners, np.float32))


def edit_corners(img, corners, title):
    """Fönster där man drar hörnen med musen. Enter/Space = klar, Esc = hoppa över."""
    h, w = img.shape[:2]
    scale = min(1.0, 900 / h, 1400 / w)
    view = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    pts = (corners * scale).tolist() if corners is not None else \
        [[50, 50], [view.shape[1] - 50, 50], [view.shape[1] - 50, view.shape[0] - 50], [50, view.shape[0] - 50]]
    state = {"drag": None}

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["drag"] = int(np.argmin([(x - px) ** 2 + (y - py) ** 2 for px, py in pts]))
        elif event == cv2.EVENT_MOUSEMOVE and state["drag"] is not None:
            pts[state["drag"]] = [x, y]
        elif event == cv2.EVENT_LBUTTONUP:
            state["drag"] = None

    cv2.namedWindow(title)
    cv2.setMouseCallback(title, on_mouse)
    while True:
        frame = view.copy()
        poly = np.array(pts, np.int32)
        cv2.polylines(frame, [poly], True, (0, 200, 0), 2, cv2.LINE_AA)
        for p in poly:
            cv2.circle(frame, tuple(int(v) for v in p), 9, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "Dra hornen. Enter = spara, Esc = hoppa over", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.imshow(title, frame)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10, 32):
            cv2.destroyWindow(title)
            return order(np.array(pts, np.float32) / scale)
        if key == 27:
            cv2.destroyWindow(title)
            return None


def warp(img, corners, ratio):
    tl, tr, br, bl = corners
    width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    landscape = width > height
    if ratio == "auto":
        out_w, out_h = int(round(width)), int(round(height))
    else:
        long_side = mm_to_px(HALF_A4_MM[1])
        short_side = int(round(long_side / ratio))
        out_w, out_h = (long_side, short_side) if landscape else (short_side, long_side)
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], np.float32)
    m = cv2.getPerspectiveTransform(corners, dst)
    out = cv2.warpPerspective(img, m, (out_w, out_h), flags=cv2.INTER_CUBIC)
    if landscape:  # en halv liggande A4 är stående – vrid så att bilden fyller den
        out = cv2.rotate(out, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return out


def to_pil(img):
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def main():
    ap = argparse.ArgumentParser(description="Räta ut papper i foton.")
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--edit", action="store_true", help="justera hörnen med musen innan sparning")
    ap.add_argument("--ratio", default="a",
                    help="'a' = A-format 1:1.414 (standard), 'auto' = uppmätt, eller ett tal, t.ex. 1.5")
    ap.add_argument("--pdf", action="store_true",
                    help="spara även A4 liggande PDF med bilden på vänstra halvan (högra tom att skriva på)")
    ap.add_argument("--dubbel", action="store_true",
                    help="som --pdf men med bilden på båda halvorna, så att ett A4 blir två kort")
    ap.add_argument("--debug", action="store_true", help="spara bild med hittade hörn utritade")
    args = ap.parse_args()

    ratio = "auto" if args.ratio == "auto" else (2 ** 0.5 if args.ratio == "a" else float(args.ratio))

    for path in args.images:
        img = load(path)
        corners = find_corners(img)
        if args.edit:
            corners = edit_corners(img, corners, path.name)
            if corners is None:
                print(f"{path.name}: hoppade över")
                continue
        elif corners is None:
            print(f"{path.name}: hittade inget papper, kör med --edit", file=sys.stderr)
            continue

        if args.debug:
            dbg = img.copy()
            cv2.polylines(dbg, [corners.astype(np.int32)], True, (0, 255, 0), 8)
            cv2.imwrite(str(path.with_name(path.stem + "_hörn.jpg")), dbg)

        out = to_pil(warp(img, corners, ratio))
        out_path = path.with_name(path.stem + "_rak.jpg")
        out.save(out_path, quality=95, dpi=(DPI, DPI))
        print(f"{path.name} -> {out_path.name}")

        if args.pdf or args.dubbel:
            page = Image.new("RGB", (mm_to_px(A4_LANDSCAPE_MM[0]), mm_to_px(A4_LANDSCAPE_MM[1])), "white")
            half_w, half_h = mm_to_px(HALF_A4_MM[0]), mm_to_px(HALF_A4_MM[1])
            fitted = ImageOps.contain(out, (half_w, half_h))
            offset = ((half_w - fitted.width) // 2, (half_h - fitted.height) // 2)
            page.paste(fitted, offset)
            if args.dubbel:
                page.paste(fitted, (page.width - half_w + offset[0], offset[1]))
            pdf_path = path.with_name(path.stem + "_A4.pdf")
            page.save(pdf_path, resolution=DPI)
            print(f"{path.name} -> {pdf_path.name}")


if __name__ == "__main__":
    main()
