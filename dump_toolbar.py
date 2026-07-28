# -*- coding: utf-8 -*-
# 补 performance_patch.py 缺失的两处顶层定义：inspector import 块 + _PREFLIGHT_ENABLED。
# 这俩不被任何安装步骤引用，故安装成功证明不了它们在，是漏网的导出体检依赖。
# 幂等：行首已有定义则跳过；备份 .bak_perf_heal2 后插在 def install(): 之前。
import os, re, shutil

path = 'performance_patch.py'
with open(path, encoding='utf-8') as f:
    text = f.read()

INSPECTOR_BLOCK = '''try:
    from ui.services.template_inspector import inspect_template as _inspect_template
    _HAS_INSPECTOR = True
except Exception:
    _inspect_template = None
    _HAS_INSPECTOR = False

'''

PREFLIGHT_BLOCK = '''_PREFLIGHT_ENABLED = os.environ.get("WS_PERF_PREFLIGHT", "1") != "0"

'''

need_inspector = not re.search(r'^_HAS_INSPECTOR\s*=', text, re.M)
need_preflight = not re.search(r'^_PREFLIGHT_ENABLED\s*=', text, re.M)

print('缺 inspector 块（_HAS_INSPECTOR/_inspect_template）:', need_inspector)
print('缺 _PREFLIGHT_ENABLED 常量:', need_preflight)

if not need_inspector and not need_preflight:
    print('\n两处都在。若导出仍炸，把点导出时的新报错贴我（按逻辑不应再有 NameError）。')
else:
    anchors = [m.start() for m in re.finditer(r'^def install\(\)\s*:', text, re.M)]
    if len(anchors) != 1:
        print('\n⚠ 锚点 def install(): 匹配 %d 处（应恰为 1），停！未修改。' % len(anchors))
    else:
        bak = path + '.bak_perf_heal2'
        shutil.copy(path, bak)
        print('已备份到', bak)
        insert = '\n# === 补回漏网的导出体检依赖（不被安装步骤引用，故此前漏补）===\n'
        if need_inspector:
            insert += INSPECTOR_BLOCK
        if need_preflight:
            insert += PREFLIGHT_BLOCK
        text = text[:anchors[0]] + insert + text[anchors[0]:]
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        print('已补回，写回完成。')