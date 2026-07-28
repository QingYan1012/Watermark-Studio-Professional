# -*- coding: utf-8 -*-
"""系统变量解析 + 注入片段（Variable Engine 地基）。

resolve_system_vars(text, ctx)：独立解析器，只动它认识的系统变量名，其余原样保留。
system_vars_fragment(index, total, path, image_size)：造全 str 的系统变量片段，供调用方
  {**data, **fragment} 合并后交给 renderer.safe_format —— 见 key 在 data 且非空即替换，
  无需改 renderer；template_unresolved_fields 吃同一份 data，系统变量不再进橙色警告。
  index/total/path/image_size 缺则对应键不加。image_size=(w,h) 为原图像素尺寸。

系统变量：
  {图片序号} 列表位置，从 1 起；批量导出时 = 导出顺序号。
  {页码}     = 图片序号（地质图册强惯例：顺序页）。若你要“每 N 张一页”或另一套编号，
             告诉我，我改这一行的取值函数即可，调用点不用动。
  {图片总数} 列表总数。
  {文件名}   文件名 stem（不含扩展名）。
  {原图宽}   原图像素宽。{原图高} 原图像素高。
  {当前日期} 渲染当天 YYYY-MM-DD。{当前时间} 当天 HH:MM:SS。
未实现、下一轮做：条件显示（语法见回复，默认提议 {?字段|文本}，可一票否决）。
未实现、挂账：响应式规则（横竖图自动调布局，需产品决策）。

自测：python -m ui.services.system_vars，预期 SELFTEST PASS。
"""
import os
import re
import time

_SYSTEM_VARS = {
    "图片序号": lambda ctx: ctx.get("index"),
    "页码":     lambda ctx: ctx.get("index"),   # 默认=序号；改语义只改这一行
    "图片总数": lambda ctx: ctx.get("total"),
    "文件名":   lambda ctx: ctx.get("stem"),
    "原图宽":   lambda ctx: ctx.get("width"),
    "原图高":   lambda ctx: ctx.get("height"),
    "当前日期": lambda ctx: time.strftime("%Y-%m-%d"),
    "当前时间": lambda ctx: time.strftime("%H:%M:%S"),
}

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def resolve_system_vars(text, ctx=None):
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    ctx = ctx or {}

    def _sub(m):
        name = m.group(1)
        getter = _SYSTEM_VARS.get(name)
        if getter is None:
            return m.group(0)
        try:
            val = getter(ctx)
        except Exception:
            return m.group(0)
        if val is None:
            return m.group(0)
        return str(val)

    try:
        return _PLACEHOLDER.sub(_sub, text)
    except Exception:
        return text


def known_system_vars():
    return list(_SYSTEM_VARS.keys())


def system_vars_fragment(index=None, total=None, path=None, image_size=None):
    frag = {}
    try:
        if index is not None:
            frag["图片序号"] = str(index)
            frag["页码"] = str(index)
        if total is not None:
            frag["图片总数"] = str(total)
        if path is not None:
            frag["文件名"] = os.path.splitext(os.path.basename(path))[0]
        frag["当前日期"] = time.strftime("%Y-%m-%d")
        frag["当前时间"] = time.strftime("%H:%M:%S")
    except Exception:
        pass
    try:
        if image_size is not None:
            frag["原图宽"] = str(int(image_size[0]))
            frag["原图高"] = str(int(image_size[1]))
    except Exception:
        pass
    return frag


if __name__ == "__main__":
    fails = []

    def check(desc, got, want):
        if got != want:
            fails.append((desc, got, want))

    def check_re(desc, got, pattern):
        if not re.search(pattern, got):
            fails.append((desc, got, "match " + pattern))

    check("序号", resolve_system_vars("{图片序号}", {"index": 3}), "3")
    check("页码", resolve_system_vars("{页码}", {"index": 3}), "3")
    check("总数", resolve_system_vars("{图片总数}", {"total": 12}), "12")
    check("文件名", resolve_system_vars("{文件名}", {"stem": "ZK304 (1)-未識別深度m"}), "ZK304 (1)-未識別深度m")
    check_re("日期格式", resolve_system_vars("{当前日期}", {}), r"^\d{4}-\d{2}-\d{2}$")
    check_re("时间格式", resolve_system_vars("{当前时间}", {}), r"^\d{2}:\d{2}:\d{2}$")
    check("混合", resolve_system_vars("第{页码}/{图片总数}页 {文件名}", {"index": 3, "total": 12, "stem": "abc"}), "第3/12页 abc")
    check("保留未知", resolve_system_vars("{钻孔编号}-{图片序号}", {"index": 3}), "{钻孔编号}-3")
    check("缺值保留", resolve_system_vars("[{图片序号}]", {}), "[{图片序号}]")
    check("无占位", resolve_system_vars("普通文字", {"index": 1}), "普通文字")
    if resolve_system_vars("{当前日期}", {}) == "{当前日期}":
        fails.append(("日期应能算", "原样", "!= 原样"))
    check("known含页码", "页码" in known_system_vars(), True)
    check("None入参", resolve_system_vars(None), "")
    check("int入参", resolve_system_vars(123), "123")
    check("resolve原图宽", resolve_system_vars("{原图宽}", {"width": 4000}), "4000")

    f = system_vars_fragment(3, 12, "/a/ZK304 (1)-x.jpg")
    check("frag序号", f.get("图片序号"), "3")
    check("frag页码", f.get("页码"), "3")
    check("frag总数", f.get("图片总数"), "12")
    check("frag文件名", f.get("文件名"), "ZK304 (1)-x")
    check("frag全str", all(isinstance(v, str) for v in f.values()), True)
    f2 = system_vars_fragment(None, 12, None)
    check("frag缺index无页码", "页码" in f2, False)
    merged = {**{"钻孔编号": "ZK805"}, **system_vars_fragment(3, 12, "a.jpg")}
    check("合并不覆盖业务字段", merged.get("钻孔编号"), "ZK805")
    f3 = system_vars_fragment(1, 1, "a.jpg", image_size=(4000, 3000))
    check("frag原图宽", f3.get("原图宽"), "4000")
    check("frag原图高", f3.get("原图高"), "3000")
    f4 = system_vars_fragment(1, 1, "a.jpg")
    check("frag无size无原图宽", "原图宽" in f4, False)

    print("== system_vars 自测 ==")
    if fails:
        print("SELFTEST FAIL: %d 项" % len(fails))
        for desc, got, want in fails:
            print("  - %s : got=%r want=%r" % (desc, got, want))
    else:
        print("SELFTEST PASS: 全过")