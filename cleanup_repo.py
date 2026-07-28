# -*- coding: utf-8 -*-
# 清理仓库：删 0 字节死占位 .py（排除 __init__.py）+ 调试残留 + 写 .gitignore。
# 不带参数：只打印清单 + 对空文件做引用检查，不删。加 --delete：执行删除/写 gitignore。
# 在 git 仓库内，删错可 git checkout 恢复，故不另做备份。
import os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DO_DELETE = '--delete' in sys.argv

# 调试/备份残留：精确名，无论大小都该删
JUNK_EXACT = {
    'dump_toolbar.py', 'dump_toolbar_out.txt', 'ui.py.golden',
    'legacy_app.py.bak_refinebatch', 'legacy_app.py.bak_theme_patch',
    'legacy_app.py.bak_rc2',
    'performance_patch.py.bak_perf_heal', 'performance_patch.py.bak_perf_heal2',
}

GITIGNORE_LINES = [
    '__pycache__/', '*.py[cod]', '*$py.class',
    '*.bak_*', '*.golden',
    'dump_toolbar.py', 'dump_toolbar_out.txt',
    '.watermark_studio/', '*.log',
    'build/', 'dist/', '*.spec',
]

def all_py_texts():
    """读所有 .py 文本，供引用检查（跳过待删的占位自身无所谓，它们空）。"""
    texts = []
    for dp, _, fns in os.walk(ROOT):
        if any(p in dp for p in ('.git', '__pycache__', '.watermark_studio')):
            continue
        for fn in fns:
            if fn.endswith('.py'):
                try:
                    with open(os.path.join(dp, fn), encoding='utf-8', errors='replace') as f:
                        texts.append(f.read())
                except Exception:
                    pass
    return texts

def is_imported(name, texts):
    """ui 根的空模块 name 是否被 import（from ui.name / from .name / from ui import name / import ui.name）。"""
    pats = [
        r'from\s+ui\s+import\b[^\n]*\b' + re.escape(name) + r'\b',
        r'from\s+ui\.' + re.escape(name) + r'\b',
        r'from\s+\.' + re.escape(name) + r'\b',
        r'import\s+ui\.' + re.escape(name) + r'\b',
    ]
    blob = '\n'.join(texts)
    return any(re.search(p, blob) for p in pats)

def main():
    texts = all_py_texts()
    empty_targets = []   # (path, imported?)
    junk_targets = []    # path

    for dp, _, fns in os.walk(ROOT):
        if any(p in dp for p in ('.git', '__pycache__', '.watermark_studio')):
            continue
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, ROOT).replace(os.sep, '/')
            if fn in JUNK_EXACT or rel in JUNK_EXACT or rel.split('/')[-1] in JUNK_EXACT:
                junk_targets.append(rel); continue
            if fn.endswith('.py') and fn != '__init__.py':
                try:
                    if os.path.getsize(full) == 0:
                        mod = fn[:-3]
                        empty_targets.append((rel, is_imported(mod, texts)))
                except Exception:
                    pass

    print('=== A. 0 字节死占位 .py（排除 __init__.py）===')
    if not empty_targets:
        print('  (无)')
    for rel, imp in empty_targets:
        flag = '⚠ 检测到 import，默认跳过' if imp else '可删'
        print('  [%s] %s' % (flag, rel))

    print('=== B. 调试/备份残留 ===')
    if not junk_targets:
        print('  (无)')
    for rel in sorted(junk_targets):
        print('  [可删] %s' % rel)

    # 真正要删的 = 无引用的空文件 + 全部残留
    to_delete = [rel for rel, imp in empty_targets if not imp] + junk_targets
    skipped = [rel for rel, imp in empty_targets if imp]

    print()
    print('将删除 %d 个文件；跳过 %d 个（有 import 引用）。' % (len(to_delete), len(skipped)))
    if skipped:
        print('  跳过列表（请人工确认这些 import 是否本就该指向空模块）：')
        for s in skipped:
            print('    -', s)

    # .gitignore
    gi = os.path.join(ROOT, '.gitignore')
    gi_action = None
    if not os.path.exists(gi):
        gi_action = '将创建 .gitignore'
    else:
        have = set(open(gi, encoding='utf-8', errors='replace').read().splitlines())
        miss = [l for l in GITIGNORE_LINES if l not in have]
        gi_action = ('.gitignore 已存在，缺 %d 条，将追加' % len(miss)) if miss else '.gitignore 已存在且条目齐全，不动'

    if not DO_DELETE:
        print('\n（未删除。确认上面清单无误后，跑 `python cleanup_repo.py --delete` 执行。）')
        print('gitignore：' + gi_action)
        return

    # 执行删除
    n = 0
    for rel in to_delete:
        try:
            os.remove(os.path.join(ROOT, rel)); n += 1
        except Exception as e:
            print('  删 %s 失败：%r' % (rel, e))
    print('已删除 %d 个文件。' % n)

    # 写/追加 .gitignore
    if not os.path.exists(gi):
        with open(gi, 'w', encoding='utf-8') as f:
            f.write('\n'.join(GITIGNORE_LINES) + '\n')
        print('已创建 .gitignore')
    else:
        have = set(open(gi, encoding='utf-8', errors='replace').read().splitlines())
        miss = [l for l in GITIGNORE_LINES if l not in have]
        if miss:
            with open(gi, 'a', encoding='utf-8') as f:
                f.write('\n# Watermark Studio 清理补充\n' + '\n'.join(miss) + '\n')
            print('已追加 %d 条到 .gitignore' % len(miss))
        else:
            print('.gitignore 无需改动')
    print('\n完成后：git add -A && git commit -m "chore: 清理占位与调试残留" && git push')

if __name__ == '__main__':
    main()