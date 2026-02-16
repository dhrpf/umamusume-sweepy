import pickle
import cv2
import numpy as np
from pathlib import Path

TEMPLATE_DIR = Path("resource/umamusume/trainingIcons")
OUTPUT_PATH = Path("resource/umamusume/trainingIcons.pkl")
BAKED_PATH = OUTPUT_PATH


def extract_circle(img):
    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2
    r = min(cx, cy) - 2
    x1, y1 = max(0, cx - r), max(0, cy - r)
    x2, y2 = min(w, cx + r), min(h, cy + r)
    return cv2.resize(img[y1:y2, x1:x2], (92, 92), interpolation=cv2.INTER_AREA)


def compute_features(img_bgr):
    sz = img_bgr.shape[0]
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    features = []
    mask_full = np.zeros((sz, sz), dtype=np.uint8)
    cv2.circle(mask_full, (sz // 2, sz // 2), sz // 2 - 8, 255, -1)
    mask_hair = np.zeros((sz, sz), dtype=np.uint8)
    mask_hair[:int(sz * 0.35), :] = mask_full[:int(sz * 0.35), :]
    mask_face = np.zeros((sz, sz), dtype=np.uint8)
    mask_face[int(sz * 0.30):int(sz * 0.65), :] = mask_full[int(sz * 0.30):int(sz * 0.65), :]
    mask_body = np.zeros((sz, sz), dtype=np.uint8)
    mask_body[int(sz * 0.65):, :] = mask_full[int(sz * 0.65):, :]
    half = sz // 2
    quadrants = [(0, 0, half, half), (half, 0, sz, half),
                 (0, half, half, sz), (half, half, sz, sz)]
    mask_ear_l = np.zeros((sz, sz), dtype=np.uint8)
    mask_ear_l[:int(sz * 0.40), :int(sz * 0.35)] = mask_full[:int(sz * 0.40), :int(sz * 0.35)]
    mask_ear_r = np.zeros((sz, sz), dtype=np.uint8)
    mask_ear_r[:int(sz * 0.40), int(sz * 0.65):] = mask_full[:int(sz * 0.40), int(sz * 0.65):]

    def hist(src, ch, bins, rng, m, weight=1.0):
        h = cv2.calcHist([src], [ch], m, [bins], rng).flatten()
        h /= (h.sum() + 1e-10)
        features.append(h * weight)

    hist(hsv, 0, 30, [0, 180], mask_full)
    hist(hsv, 1, 12, [0, 256], mask_full)
    hist(lab, 0, 12, [0, 256], mask_full)
    hist(lab, 1, 12, [0, 256], mask_full)
    hist(lab, 2, 12, [0, 256], mask_full)
    quad_weights = [1.5, 1.5, 0.5, 0.5]
    for qi, (x1, y1, x2, y2) in enumerate(quadrants):
        w = quad_weights[qi]
        mask_q = np.zeros((sz, sz), dtype=np.uint8)
        mask_q[y1:y2, x1:x2] = mask_full[y1:y2, x1:x2]
        hist(hsv, 0, 20, [0, 180], mask_q, w)
        hist(hsv, 1, 8, [0, 256], mask_q, w)
        hist(lab, 1, 8, [0, 256], mask_q, w)
        hist(lab, 2, 8, [0, 256], mask_q, w)
    hist(hsv, 0, 30, [0, 180], mask_hair, 4.0)
    hist(hsv, 1, 16, [0, 256], mask_hair, 4.0)
    hist(lab, 0, 12, [0, 256], mask_hair, 3.0)
    hist(lab, 1, 16, [0, 256], mask_hair, 4.0)
    hist(lab, 2, 16, [0, 256], mask_hair, 4.0)
    for mask_ear in [mask_ear_l, mask_ear_r]:
        hist(hsv, 0, 20, [0, 180], mask_ear, 3.0)
        hist(hsv, 1, 10, [0, 256], mask_ear, 3.0)
        hist(lab, 1, 10, [0, 256], mask_ear, 3.0)
        hist(lab, 2, 10, [0, 256], mask_ear, 3.0)
    hist(hsv, 0, 20, [0, 180], mask_face, 2.0)
    hist(hsv, 1, 12, [0, 256], mask_face, 2.0)
    hist(lab, 1, 12, [0, 256], mask_face, 2.0)
    hist(lab, 2, 12, [0, 256], mask_face, 2.0)
    hist(hsv, 0, 16, [0, 180], mask_body, 0.5)
    hist(hsv, 1, 8, [0, 256], mask_body, 0.5)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    angle = (np.arctan2(gy, gx) * 180 / np.pi + 180) % 360
    for mask_r, n_bins, w in [(mask_hair, 18, 3.0), (mask_full, 18, 1.0), (mask_face, 12, 1.5)]:
        mb = mask_r > 0
        mg, ag = mag[mb], angle[mb]
        if len(mg) > 0:
            hog = np.zeros(n_bins, dtype=np.float32)
            bins = (ag / (360.0 / n_bins)).astype(int) % n_bins
            np.add.at(hog, bins, mg)
            hog /= (hog.sum() + 1e-10)
            features.append(hog * w)
        else:
            features.append(np.zeros(n_bins, dtype=np.float32))
    for mask_ear in [mask_ear_l, mask_ear_r]:
        mb = mask_ear > 0
        mg, ag = mag[mb], angle[mb]
        if len(mg) > 0:
            hog = np.zeros(12, dtype=np.float32)
            bins = (ag / 30.0).astype(int) % 12
            np.add.at(hog, bins, mg)
            hog /= (hog.sum() + 1e-10)
            features.append(hog * 3.0)
        else:
            features.append(np.zeros(12, dtype=np.float32))
    hair_crop = gray[:int(sz * 0.40), :]
    hair_mask_crop = mask_full[:int(sz * 0.40), :]
    hair_masked = cv2.bitwise_and(hair_crop, hair_mask_crop)
    hair_small = cv2.resize(hair_masked, (12, 8), interpolation=cv2.INTER_AREA)
    features.append(hair_small.flatten().astype(np.float32) / 255.0 * 2.0)
    edges = cv2.Canny(gray, 50, 120)
    hair_edges = cv2.bitwise_and(edges, mask_hair)
    hair_edges_small = cv2.resize(hair_edges, (16, 8), interpolation=cv2.INTER_AREA)
    features.append(hair_edges_small.flatten().astype(np.float32) / 255.0 * 3.0)
    for mask_ear in [mask_ear_l, mask_ear_r]:
        ear_edges = cv2.bitwise_and(edges, mask_ear)
        ear_edges_small = cv2.resize(ear_edges, (8, 8), interpolation=cv2.INTER_AREA)
        features.append(ear_edges_small.flatten().astype(np.float32) / 255.0 * 3.0)
    face_edges = cv2.bitwise_and(edges, mask_face)
    face_edges_small = cv2.resize(face_edges, (12, 8), interpolation=cv2.INTER_AREA)
    features.append(face_edges_small.flatten().astype(np.float32) / 255.0 * 2.0)
    full_edges = cv2.bitwise_and(edges, mask_full)
    full_edges_small = cv2.resize(full_edges, (16, 16), interpolation=cv2.INTER_AREA)
    features.append(full_edges_small.flatten().astype(np.float32) / 255.0)
    mag_u8 = np.clip(mag, 0, 255).astype(np.uint8)
    mag_masked = cv2.bitwise_and(mag_u8, mask_hair)
    mag_small = cv2.resize(mag_masked, (14, 8), interpolation=cv2.INTER_AREA)
    features.append(mag_small.flatten().astype(np.float32) / 255.0 * 2.0)
    return np.concatenate(features).astype(np.float32)


def bake():
    if not TEMPLATE_DIR.exists():
        print(f"Template directory not found: {TEMPLATE_DIR}")
        return False
    sift = cv2.SIFT_create(nfeatures=100)
    names = []
    feat_list = []
    sift_des_list = []
    for p in sorted(TEMPLATE_DIR.glob("*.png")):
        img = cv2.imread(str(p))
        if img is None:
            continue
        portrait = extract_circle(img)
        feat = compute_features(portrait)
        gray = cv2.cvtColor(portrait, cv2.COLOR_BGR2GRAY)
        sz = portrait.shape[0]
        mask = np.zeros((sz, sz), dtype=np.uint8)
        cv2.circle(mask, (sz // 2, sz // 2), sz // 2 - 6, 255, -1)
        kp, des = sift.detectAndCompute(gray, mask)
        names.append(p.stem)
        feat_list.append(feat)
        sift_des_list.append(des)
    feat_stack = np.stack(feat_list)
    norms = np.linalg.norm(feat_stack, axis=1, keepdims=True)
    feat_normed = feat_stack / np.maximum(norms, 1e-10)
    data = {
        "names": names,
        "feat_normed": feat_normed,
        "sift_descriptors": {n: d for n, d in zip(names, sift_des_list)},
    }
    with open(OUTPUT_PATH, "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Baked {len(names)} templates -> {OUTPUT_PATH}")
    return True


if __name__ == "__main__":
    bake()
