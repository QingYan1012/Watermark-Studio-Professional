# -- coding: utf-8 --
"""路3 训练管线：把 label_corners_v3 标的 *.corners.json 转成 YOLOv8-pose 数据集，
并给出一键训练+导出 ONNX。独立运行，不 import 主软件。
关键点目标 = json 里的 keypoints_fixed（定长 20 = 4角+每边4，顺序固定），
天然表达弯曲/变形边，不假设矩形。
依赖分层（务必看清，别被 torch 吓到）：
  - 本脚本“建数据集/自检”只需标准库 + Pillow（你已有）。
  - --train 才需要 ultralytics（会拉 torch，几个 GB，【只在开发机，不进打包 exe】）。
  - 最终进分发包的只有导出的 .onnx(约6MB) + onnxruntime(约10~15MB)。
设计要点：
  - 关镜像增强(fliplr/flipud=0)：我们顶点顺序无稳定镜像语义，开镜像会喂错标签。
  - 用 train.txt/val.txt 图片列表 + 标准 images/labels 镜像目录，ultralytics 配对最稳。
  - --viz 先把每张标注的 20 点画出来存 viz/，训练前肉眼扫一眼，避免“错标签训错模型”。
用法：
  python train_corners.py <标注文件夹> --viz                 # 先自检标注
  python train_corners.py <标注文件夹> --train --epochs 200  # 建集+训练+导出 onnx
"""
import os, sys, json, glob, random, shutil, argparse
from PIL import Image, ImageDraw

K = 4  # 与 label_corners_v3 一致：每边重采样内部点数 → 定长 4+4K=20
EDGE_COL = ["#3ea6ff", "#2faa55", "#f0b440", "#9b7bff"]


def _load_pairs(folder):
    """返回 [(json_path, image_path, payload)]，用 json 内 image 字段定位图片，最稳。"""
    pairs = []
    for jp in sorted(glob.glob(os.path.join(folder, "*.corners.json"))):
        try:
            with open(jp, encoding="utf-8") as f:
                pay = json.load(f)
        except Exception:
            continue
        img_name = pay.get("image") or (os.path.basename(jp).replace(".corners.json", ""))
        ip = os.path.join(folder, img_name)
        if not os.path.exists(ip):
            # 兜底：按 json 的 stem 找同 stem 的图
            stem = os.path.splitext(os.path.basename(jp))[0]
            cand = glob.glob(os.path.join(folder, stem + ".*"))
            cand = [c for c in cand if not c.lower().endswith(".json")]
            ip = cand[0] if cand else ip
        if os.path.exists(ip):
            pairs.append((jp, ip, pay))
    return pairs


def _kp_to_yolo(pay, w, h):
    """keypoints_fixed(20点, 已是 0~1 rel) → (cx,cy,bw,bh, [x,y,v]*20) 全归一化。"""
    kp = pay.get("keypoints_fixed") or []
    if len(kp) < 4 + 4 * K:
        return None
    kp = kp[:4 + 4 * K]
    xs = [p[0] for p in kp]; ys = [p[1] for p in kp]
    minx, maxx = min(xs), max(xs); miny, maxy = min(ys), max(ys)
    cx = (minx + maxx) * 0.5; cy = (miny + maxy) * 0.5
    bw = max(1e-4, maxx - minx); bh = max(1e-4, maxy - miny)
    flat = [cx, cy, bw, bh]
    for p in kp:
        flat += [max(0.0, min(1.0, p[0])), max(0.0, min(1.0, p[1])), 2.0]  # 可见性=2
    return flat


def _viz_one(ip, pay, out_path):
    im = Image.open(ip).convert("RGB")
    w, h = im.size
    sc = min(1000 / w, 1000 / h, 1.0)
    dw, dh = max(1, round(w * sc)), max(1, round(h * sc))
    im2 = im.resize((dw, dh), Image.BILINEAR)
    d = ImageDraw.Draw(im2)
    kp = (pay.get("keypoints_fixed") or [])[:4 + 4 * K]
    cr = pay.get("corners_rel") or []
    # 四角连线
    if len(cr) == 4:
        for i in range(4):
            a = cr[i]; b = cr[(i + 1) % 4]
            d.line([a[0] * dw, a[1] * dh, b[0] * dw, b[1] * dh], fill="#ffb347", width=2)
    # 20 关键点：角点橙、边点按边着色
    for i, p in enumerate(kp):
        x, y = p[0] * dw, p[1] * dh
        if i % (K + 1) == 0:
            d.ellipse([x - 6, y - 6, x + 6, y + 6], fill="#ffb347", outline="white")
        else:
            col = EDGE_COL[(i // (K + 1)) % 4]
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=col, outline="white")
    im2.save(out_path)


def build_dataset(folder, out_root, val_ratio=0.2, seed=7):
    pairs = _load_pairs(folder)
    if not pairs:
        print("[ERROR] 没找到任何 *.corners.json 或对应图片。"); return None
    random.seed(seed); random.shuffle(pairs)
    n_val = max(1, int(len(pairs) * val_ratio)) if len(pairs) >= 5 else 0
    val_pairs, train_pairs = pairs[:n_val], pairs[n_val:]
    os.makedirs(os.path.join(out_root, "images", "train"), exist_ok=True)
    os.makedirs(os.path.join(out_root, "images", "val"), exist_ok=True)
    os.makedirs(os.path.join(out_root, "labels", "train"), exist_ok=True)
    os.makedirs(os.path.join(out_root, "labels", "val"), exist_ok=True)
    train_txt, val_txt = [], []
    skipped = 0
    for split, sub_pairs, txt in (("train", train_pairs, train_txt), ("val", val_pairs, val_txt)):
        for jp, ip, pay in sub_pairs:
            try:
                w, h = Image.open(ip).size
            except Exception:
                skipped += 1; continue
            row = _kp_to_yolo(pay, w, h)
            if row is None:
                skipped += 1; continue
            stem = os.path.splitext(os.path.basename(ip))[0]
            ext = os.path.splitext(ip)[1] or ".jpg"
            img_dst = os.path.join(out_root, "images", split, stem + ext)
            if not os.path.exists(img_dst):
                shutil.copyfile(ip, img_dst)
            lbl_dst = os.path.join(out_root, "labels", split, stem + ".txt")
            with open(lbl_dst, "w", encoding="utf-8") as f:
                f.write("0 " + " ".join(f"{v:.6f}" for v in row) + "\n")
            txt.append(os.path.abspath(img_dst))
    with open(os.path.join(out_root, "train.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(train_txt))
    with open(os.path.join(out_root, "val.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(val_txt))
    yaml_path = os.path.join(out_root, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(f"path: {os.path.abspath(out_root)}\n")
        f.write("train: train.txt\nval: val.txt\n")
        f.write(f"kpt_shape: [{4 + 4 * K}, 3]\n")
        f.write(f"flip_idx: {list(range(4 + 4 * K))}\n")  # 占位；镜像增强已关，不生效
        f.write("nc: 1\nnames: ['core_box']\n")
    print(f"[OK] 数据集建成：train {len(train_txt)} 张 / val {len(val_txt)} 张 / 跳过 {skipped}")
    print(f"     -> {yaml_path}")
    return yaml_path


def viz(folder, out_dir):
    pairs = _load_pairs(folder)
    os.makedirs(out_dir, exist_ok=True)
    for jp, ip, pay in pairs:
        _viz_one(ip, pay, os.path.join(out_dir, os.path.basename(ip)))
    print(f"[OK] 标注自检图 {len(pairs)} 张 -> {out_dir}  （肉眼看四角顺序/边点有没有飞出去）")


def train(yaml_path, epochs, imgsz, batch, project):
    try:
        from ultralytics import YOLO
    except Exception:
        print("[ERROR] 训练需要 ultralytics（会拉 torch，只在开发机，不进打包 exe）。\n"
              "        请先：pip install ultralytics")
        sys.exit(3)
    m = YOLO("yolov8n-pose.pt")
    # fliplr/flipud=0：关镜像增强（顶点顺序无稳定镜像语义，开镜像会喂错标签）
    m.train(data=yaml_path, epochs=epochs, imgsz=imgsz, batch=batch,
            fliplr=0.0, flipud=0.0, project=project, name="core_box_pose",
            patience=40, workers=2, exist_ok=True)
    best = os.path.join(project, "core_box_pose", "weights", "best.pt")
    m2 = YOLO(best)
    onnx_path = m2.export(format="onnx", imgsz=imgsz, simplify=True)
    print(f"[OK] 训练完成，ONNX 导出 -> {onnx_path}")
    print("     下一步：python persp_model.py <某张图> <这个.onnx> 独立验证准不准")
    return onnx_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="标注文件夹(含 *.corners.json 与图片)")
    ap.add_argument("--viz", action="store_true", help="只画标注自检图，不建集不训练")
    ap.add_argument("--train", action="store_true", help="建集+训练+导出 onnx(需 ultralytics)")
    ap.add_argument("--out", default="dataset", help="数据集输出目录")
    ap.add_argument("--vizdir", default="label_viz")
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--project", default="runs")
    a = ap.parse_args()

    pairs = _load_pairs(a.folder)
    print(f"找到标注 {len(pairs)} 张。经验值：pose 小样本建议 ≥30 张、覆盖各种角度/光照/变形/遮挡；不够就补标重跑。")
    if a.viz or (not a.train):
        viz(a.folder, os.path.join(a.folder, a.vizdir) if not os.path.isabs(a.vizdir) else a.vizdir)
    if a.train:
        yp = build_dataset(a.folder, a.out)
        if yp:
            train(yp, a.epochs, a.imgsz, a.batch, a.project)


if __name__ == "__main__":
    main()