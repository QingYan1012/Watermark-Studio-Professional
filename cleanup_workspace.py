# -- coding: utf-8 --
"""清理工作目录里的一次性 overlay 生成器 / 旧标点工具 / 旧备份。
默认 dry-run（只列出将删什么，绝不删）；加 --apply 才真删，且真删前会先把
当前 ui.py 存成 ui.py.golden 兜底。想保留某个生成器以备重打：--keep 文件名。
删除用通配模式 + 保护名单双保险，绝不碰核心业务文件 / 模型线工具 / dataset / runs / 标注数据。
用法：
  python cleanup_workspace.py                 # 只看不删，先核对清单
  python cleanup_workspace.py --apply         # 核对无误后真删（自动先建 ui.py.golden）
  python cleanup_workspace.py --apply --keep add_bendsnap.py   # 排除个别不删
"""
import os, sys, glob, shutil, argparse

# 通配模式：匹配“一次性生成器/旧工具/旧备份”。核心/模型线文件无任何匹配这些前缀/后缀。
PATTERNS = ["add_*.py", "fix_*.py", "patch_*.py", "finalize_*.py",
            "label_corners.py", "label_corners_v2.py", "*.bak"]

# 保护名单：即便被模式误匹配也绝不删（双保险）。
PROTECT = {
    "main.py", "ui.py", "ui.py.golden", "renderer.py", "model.py", "data_import.py",
    "font_manager.py", "library.py", "sort_utils.py", "generate_icon.py", "build.bat",
    "requirements.txt", "app.ico", "README.md",
    "train_corners.py", "persp_model.py", "label_corners_v3.py",   # 模型线工具
    "cleanup_workspace.py",
}

# 这些是“确认保留”的代表，dry-run 时点名打印，方便你核对没被误删。
KEEP_SHOW = ["ui.py", "train_corners.py", "persp_model.py", "label_corners_v3.py",
             "renderer.py", "model.py", "data_import.py", "font_manager.py",
             "library.py", "sort_utils.py", "main.py", "build.bat", "requirements.txt"]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真删（默认只 dry-run）")
    ap.add_argument("--keep", nargs="*", default=[], help="排除不删的文件名，如 --keep add_bendsnap.py")
    a = ap.parse_args()
    keep = set(a.keep or [])

    # 收集候选
    cand = []
    protected_hit = []
    for pat in PATTERNS:
        for p in glob.glob(os.path.join(here, pat)):
            name = os.path.basename(p)
            if not os.path.isfile(p):
                continue
            if name in PROTECT:
                protected_hit.append(name); continue
            if name in keep:
                protected_hit.append(name + " (--keep)"); continue
            cand.append(p)
    cand = sorted(set(cand))

    cache_dir = os.path.join(here, "__pycache__")
    has_cache = os.path.isdir(cache_dir)

    print("==== 清理预览（dry-run，未删除任何文件）====" if not a.apply
          else "==== 开始清理 ====")
    print(f"  将删除 {len(cand)} 个文件：")
    for p in cand:
        print("    -", os.path.basename(p))
    if has_cache:
        print("    - __pycache__/  （缓存，删了自动重建，纯为整洁）")
    if protected_hit:
        print("  被保护/排除（不删）：", protected_hit)
    print("  确认保留（不在删除模式内，仅点名核对）：")
    for n in KEEP_SHOW:
        print("    ✓", n, "" if os.path.exists(os.path.join(here, n)) else "  <-- 不存在!")
    print("    ✓ dataset/  runs/  数据表参考.xlsx  app.ico  README.md")

    if not a.apply:
        print("\n[DRY-RUN] 以上仅为预览。核对无误后执行：python cleanup_workspace.py --apply")
        print("  想保留某个生成器以备重打：加 --keep 文件名（可多个）。")
        print("  --apply 会先把当前 ui.py 存成 ui.py.golden 兜底，再删。")
        return

    # ---- 真删 ----
    ui = os.path.join(here, "ui.py")
    golden = os.path.join(here, "ui.py.golden")
    if os.path.exists(ui) and not os.path.exists(golden):
        shutil.copyfile(ui, golden)
        print(f"[SAFE] 已把当前 ui.py 存为黄金存档 -> {golden}")
    elif os.path.exists(golden):
        print(f"[SAFE] ui.py.golden 已存在，未覆盖（如需更新请手动删 golden 后重跑）。")

    n = 0
    for p in cand:
        try:
            os.remove(p); n += 1
        except Exception as e:
            print("  [skip 删除失败]", os.path.basename(p), "->", e)
    if has_cache:
        try:
            shutil.rmtree(cache_dir); print("  [cleaned] __pycache__/")
        except Exception as e:
            print("  [skip 缓存清理失败]", e)
    print(f"[OK] 已删除 {n} 个文件。ui.py 未受影响；dataset/ runs/ 标注数据 均未触碰。")


if __name__ == "__main__":
    main()