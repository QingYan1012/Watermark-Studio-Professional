# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 模板体检（Template Inspector，readmes V3.0 ④ 的地基）。

纯函数、零 UI 依赖：给一个 template + 一张图的【原图尺寸】+ 一行 data，
返回一组 Issue（诊断项）。检查“导出后才会暴露”的隐患，让问题在导出前可见：

- ELEM_OUT_OF_BOUNDS  元素 bbox 超出图片 0~1 框 → 导出可能被裁切（readmes“Logo 超出边界”）
- FONT_TOO_SMALL      文字按原图像素算的字号过小 → 打印/缩小后难辨（readmes“字号过小”）
- IMAGE_PATH_MISSING  图标 path 非空但文件不存在 → 导出时该图标不显示
- ELEMENT_TOO_SMALL   图标/形状宽或高比例过小 → 几乎不可见
- PLACEHOLDER_UNRESOLVED  文字含 {字段} 但 data 没填 → 导出会原样留下花括号

设计要点：
- 用原图尺寸算像素（导出走原图全质量，体检必须对齐导出口径，而非预览小图）。
- 平铺/对角文字(tile/diagonal)的 bbox 是占位小框，不按越界判（否则会误报满屏平铺）。
- 越界给 1px 容差，避免描边/浮点造成的 1 像素误报。
- 每个检查独立 try 包裹：单项算炸不影响其余，inspector 永不抛、永不阻断调用方。

本轮（第28轮）只建本文件 + 自证；不接任何 UI/导出。下一轮再接“导出前体检提示”。

自测：
    在项目根目录运行（会拉起 ui 包但不启动 GUI）：
        python -m ui.services.template_inspector
    若环境拉起 ui 包异常，可用等价命令（不触发 ui 包，需把项目根放进 PYTHONPATH）：
        set PYTHONPATH=. && python ui\\services\\template_inspector.py
    预期末尾打印：SELFTEST PASS: 4 类检查均触发
"""

import os
from dataclasses import dataclass

from renderer import get_element_bbox, template_unresolved_fields


# ----------------------------------------------------------------------
# 诊断项（frozen dataclass：不可变、可哈希、便于跨图聚合计数）
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Issue:
    level: str       # "warn" | "info"
    code: str        # 机器可读，便于跨图聚合 / 将来“自动修正”按 code 分发
    elem_name: str   # 出问题的元素名（人类可读）
    message: str     # 人类可读说明


# ----------------------------------------------------------------------
# 阈值（经验值；将来可移到 app/config.py 做成可调）
# ----------------------------------------------------------------------
_MIN_FONT_PX_WARN = 12     # 原图像素字号 < 此值：打印/缩小后大概率难辨 → warn
_MIN_FONT_PX_INFO = 20     # 原图像素字号 < 此值：导出小图时留意 → info
_MIN_REL_SIZE = 0.005      # 图标/形状 宽或高比例 < 此值：几乎不可见 → info
_BOUNDS_TOL_PX = 1.0       # 越界判定容差（像素），吸收描边/取整的 1px 抖动


def inspect_template(template, image_size, data=None, font_manager=None):
    """
    体检一个模板在指定原图尺寸 + 一行 data 下的隐患。

    参数：
        template     : model.Template（duck typing：需有 .elements）
        image_size   : (W, H) 原图像素尺寸（导出口径）
        data         : dict，当前图对应的一行数据（用于占位符检查；可空）
        font_manager : 可空；空则文字 bbox 用默认字体估算（足够判断越界/字号）

    返回：
        List[Issue]（无隐患则为空列表；本函数永不抛异常）
    """
    issues = []

    try:
        W, H = image_size
    except Exception:
        return issues
    if W <= 0 or H <= 0:
        return issues

    data = data or {}
    elems = getattr(template, "elements", None) or []

    # ---- 占位符未匹配（整模板级，renderer 已按元素名归并） ----
    try:
        unresolved = template_unresolved_fields(template, data) or {}
    except Exception:
        unresolved = {}
    for name, fields in unresolved.items():
        if fields:
            issues.append(Issue(
                "warn", "PLACEHOLDER_UNRESOLVED", name,
                "占位符未匹配数据：" + "、".join("{%s}" % f for f in fields),
            ))

    # ---- 逐元素检查 ----
    for elem in elems:
        name = getattr(elem, "name", None) or getattr(elem, "type", "?")
        etype = getattr(elem, "type", None)

        # 图标路径缺失
        if etype == "image":
            p = (getattr(elem, "path", "") or "").strip()
            if p and not os.path.exists(p):
                issues.append(Issue(
                    "warn", "IMAGE_PATH_MISSING", name,
                    "图标文件不存在，导出时不会显示：%s" % p,
                ))

        # 图标/形状尺寸过小
        if etype in ("image", "shape"):
            try:
                wr = float(getattr(elem, "w_rel", 0) or 0)
                hr = float(getattr(elem, "h_rel", 0) or 0)
            except Exception:
                wr = hr = 0.0
            if (0 < wr < _MIN_REL_SIZE) or (0 < hr < _MIN_REL_SIZE):
                issues.append(Issue(
                    "info", "ELEMENT_TOO_SMALL", name,
                    "元素尺寸过小（宽%.3f 高%.3f），可能几乎不可见" % (wr, hr),
                ))

        # 文字字号过小（按原图像素算）
        if etype == "text":
            try:
                fpx = float(getattr(elem, "font_size_rel", 0) or 0) * H
            except Exception:
                fpx = 0.0
            if 0 < fpx < _MIN_FONT_PX_WARN:
                issues.append(Issue(
                    "warn", "FONT_TOO_SMALL", name,
                    "字号过小（约%.0fpx），打印或缩小后可能无法辨认" % fpx,
                ))
            elif 0 < fpx < _MIN_FONT_PX_INFO:
                issues.append(Issue(
                    "info", "FONT_SMALLISH", name,
                    "字号偏小（约%.0fpx），导出小图时留意" % fpx,
                ))

        # 越界（平铺/对角文字跳过：其 bbox 是占位小框，不按越界判）
        if etype == "text" and getattr(elem, "mode", "single") in ("tile", "diagonal"):
            continue
        try:
            x0, y0, x1, y1 = get_element_bbox(
                elem, (W, H), data=data, font_manager=font_manager,
            )
        except Exception:
            continue
        out = []
        if x0 < -_BOUNDS_TOL_PX:
            out.append("左")
        if y0 < -_BOUNDS_TOL_PX:
            out.append("上")
        if x1 > W + _BOUNDS_TOL_PX:
            out.append("右")
        if y1 > H + _BOUNDS_TOL_PX:
            out.append("下")
        if out:
            issues.append(Issue(
                "warn", "ELEM_OUT_OF_BOUNDS", name,
                "元素超出图片边界（%s），导出可能被裁切" % "、".join(out),
            ))

    return issues


def summarize(issues, max_lines=8):
    """
    把【单张图】的 issues 压成多行提示串（warn 优先、info 次要、限行数防刷屏）。
    无 issue 返回空串。

    注：跨图聚合（如“{钻孔编号} 未匹配：12 张”）由调用方在批量场景自行统计，
    本函数只负责单张可读化，职责单一。
    """
    if not issues:
        return ""

    warns = [i for i in issues if i.level == "warn"]
    infos = [i for i in issues if i.level == "info"]

    lines = []
    if warns:
        lines.append("⚠ 模板体检发现 %d 处警告：" % len(warns))
    for i in warns[:max_lines]:
        lines.append("  · [%s] %s" % (i.elem_name, i.message))
    if len(warns) > max_lines:
        lines.append("  · …另有 %d 处警告未列出" % (len(warns) - max_lines))

    room = max(0, max_lines - min(len(warns), max_lines))
    for i in infos[:room]:
        lines.append("  · (提示) [%s] %s" % (i.elem_name, i.message))

    return "\n".join(lines)


# ======================================================================
# 自测：构造“故意有毛病”的临时模板，正向证明四类检查均触发。
# 不依赖任何真实文件、不弹窗、不写盘。
# ======================================================================
if __name__ == "__main__":
    from model import Template, TextElement, ImageElement

    t = Template(name="自测模板")
    # 右下角文字 → bbox 必出右/下界
    t.add(TextElement(content="越界文字", x=0.95, y=0.5,
                      font_size_rel=0.05, name="越界字"))
    # 6px 小字 + 含未匹配占位符 → 同时触发 FONT_TOO_SMALL 与 PLACEHOLDER_UNRESOLVED
    t.add(TextElement(content="小字{缺字段}", x=0.1, y=0.1,
                      font_size_rel=0.002, name="小字"))
    # 不存在的图标路径 → IMAGE_PATH_MISSING（尺寸正常，不触发 TOO_SMALL/越界）
    t.add(ImageElement(path=r"C:\__wsp_no_such_file__.png",
                       x=0.1, y=0.5, w_rel=0.1, h_rel=0.1, name="坏图标"))

    issues = inspect_template(t, (4000, 3000), data={})

    print("== template_inspector 自测 ==")
    for i in issues:
        print("  [%-4s] %-22s %-10s %s" % (i.level, i.code, i.elem_name, i.message))

    codes = [i.code for i in issues]
    expect = [
        "ELEM_OUT_OF_BOUNDS",
        "FONT_TOO_SMALL",
        "PLACEHOLDER_UNRESOLVED",
        "IMAGE_PATH_MISSING",
    ]
    missing = [c for c in expect if c not in codes]

    print("----")
    if missing:
        print("SELFTEST FAIL: 缺少预期 code:", missing)
    else:
        print("SELFTEST PASS: 4 类检查均触发（越界/小字号/未匹配占位符/坏图标路径）")

    # 顺带验证 summarize 不崩、且 warn 优先
    print("---- summarize() ----")
    print(summarize(issues) or "(空)")