# -- coding: utf-8 --
"""路3 推理壳（独立验证用，本轮【不】接主软件）：onnx 软依赖，读 yolov8n-pose 导出的
onnx，返回 4角+每边4点(与软件 mesh 同构)，并画验证图。
鲁棒性设计（绕开 ultralytics 各版本 onnx 输出差异）：
  - 不依赖 bbox 是 xywh 还是 xyxy：定位全靠 20 关键点，bbox 列直接忽略。
  - 兼容已NMS(1,N,65) 与 未NMS(1,65,8400) 两种 layout：统一转成 (M,65) 取 conf 最大行。
  - 兼容关键点在 letterbox 空间 或 原图空间：启发式按坐标量级判断是否反 letterbox。
列布局固定 [0:4]=bbox(忽略) [4]=conf [5:65]=20关键点*(x,y,c)。
软依赖：没装 onnxruntime / 没给模型 → HAS_ORT=False，detect 返回 None。
用法（独立验证）：python persp_model.py <图.jpg> <模型.onnx> [输出_pred.jpg]
"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw

K = 4
N_KP = 4 + 4 * K            # 20
VEC = 4 + 1 + N_KP * 3      # 65
EDGE_COL = ["#3ea6ff", "#2faa55", "#f0b440", "#9b7bff"]

try:
    import onnxruntime as _ort
    HAS_ORT = True
except Exception:
    _ort = None
    HAS_ORT = False


def _letterbox(pil_rgb, target=640):
    w0, h0 = pil_rgb.size
    s = min(target / w0, target / h0)
    nw, nh = max(1, round(w0 * s)), max(1, round(h0 * s))
    arr = np.asarray(pil_rgb.resize((nw, nh), Image.BILINEAR), dtype=np.float32) / 255.0
    pad_w, pad_h = target - nw, target - nh
    top, left = pad_h // 2, pad_w // 2
    canvas = np.full((target, target, 3), 114 / 255.0, dtype=np.float32)
    canvas[top:top + nh, left:left + nw] = arr
    blob = canvas.transpose(2, 0, 1)[None].astype(np.float32)   # 1,3,H,W
    return blob, s, left, top, w0, h0


def _decode_row(row, s, left, top, w0, h0):
    """row: (65,) → (corners_rel[4], edge_rel{4:[4]})。启发式判 letterbox/原图空间。"""
    kpts = row[5:].reshape(N_KP, 3)
    xs = kpts[:, 0]; ys = kpts[:, 1]
    in_letterbox = (xs.max() <= 640 * 1.05 and ys.max() <= 640 * 1.05)

    def to_rel(x, y):
        if in_letterbox:
            x = (x - left) / s
            y = (y - top) / s
        return max(0.0, min(1.0, x / w0)), max(0.0, min(1.0, y / h0))

    rel = [to_rel(float(xs[i]), float(ys[i])) for i in range(N_KP)]
    corners = [rel[0], rel[K + 1], rel[2 * (K + 1)], rel[3 * (K + 1)]]
    edges = {}
    for e in range(4):
        base = e * (K + 1)
        edges[e] = [list(rel[base + 1 + j]) for j in range(K)]
    return corners, edges


def detect(pil_image, model_path, conf_thr=0.25, target=640):
    """返回 (corners_rel, edge_rel) 或 None。软依赖：无 ort/无模型 → None。"""
    if not HAS_ORT or not model_path or not os.path.exists(model_path):
        return None
    blob, s, left, top, w0, h0 = _letterbox(pil_image.convert("RGB"), target)
    sess = _ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    out = sess.run(None, {sess.get_inputs()[0].name: blob})
    y = out[0]
    if y.ndim == 3:
        y = y[0]
    if y.shape[0] == VEC and y.shape[-1] != VEC:   # (65, M) 未NMS
        y = y.T
    if y.ndim != 2 or y.shape[1] != VEC:
        return None                                  # 输出布局无法识别
    conf = y[:, 4]
    if conf.size == 0:
        return None
    i = int(np.argmax(conf))
    if float(conf[i]) < conf_thr:
        return None
    return _decode_row(y[i], s, left, top, w0, h0)


def draw_pred(pil_image, corners, edges, out_path):
    im = pil_image.convert("RGB")
    w, h = im.size
    sc = min(1200 / w, 1200 / h, 1.0)
    dw, dh = max(1, round(w * sc)), max(1, round(h * sc))
    im2 = im.resize((dw, dh), Image.BILINEAR)
    d = ImageDraw.Draw(im2)
    for e in range(4):
        chain = [corners[e]] + edges.get(e, []) + [corners[(e + 1) % 4]]
        pts = [(p[0] * dw, p[1] * dh) for p in chain]
        for j in range(len(pts) - 1):
            d.line([pts[j][0], pts[j][1], pts[j + 1][0], pts[j + 1][1]], fill=EDGE_COL[e], width=2)
        for p in edges.get(e, []):
            x, y = p[0] * dw, p[1] * dh
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=EDGE_COL[e], outline="white")
    for p in corners:
        x, y = p[0] * dw, p[1] * dh
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill="#ffb347", outline="white", width=2)
    im2.save(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：python persp_model.py <图.jpg> <模型.onnx> [输出_pred.jpg]")
        print("  没装 onnxruntime 时：pip install onnxruntime  （这只进分发包约10~15MB，不含 torch）")
        sys.exit(1)
    ip, mp = sys.argv[1], sys.argv[2]
    op = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(ip)[0] + "_pred.jpg"
    if not HAS_ORT:
        print("[WARN] 未安装 onnxruntime，无法推理。pip install onnxruntime")
        sys.exit(2)
    res = detect(Image.open(ip), mp)
    if res is None:
        print("[INFO] 模型未检测到箱子（conf 低于阈值或布局不匹配）。")
    else:
        corners, edges = res
        draw_pred(Image.open(ip), corners, edges, op)
        print(f"[OK] 检测成功，验证图 -> {op}")