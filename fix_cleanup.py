# -*- coding: utf-8 -*-
# 修复清理：删占位/残留（幂等）+ 写 .gitignore + git add -A（关键：暂存删除）+ commit。
# 跑完后你只需 git push。
import os, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

if not os.path.isdir('.git'):
    print('⚠ 当前目录不是 git 仓库（没有 .git）。请在仓库根目录跑，或改用 GitHub 网页手动删除。')
    sys.exit(1)

TARGETS = [
    'ui/left_panel.py', 'ui/right_panel.py', 'ui/toolbar.py', 'ui/bottom_bar.py',
    'ui/canvas_panel.py', 'ui/main_window.py', 'ui/rulers.py', 'ui/theme_controller.py', 'ui/toast.py',
    'dump_toolbar.py', 'dump_toolbar_out.txt', 'ui.py.golden',
    'performance_patch.py.bak_perf_heal', 'performance_patch.py.bak_perf_heal2',
    'ui/legacy_app.py.bak_refinebatch', 'ui/legacy_app.py.bak_theme_patch',
]

GITIGNORE_LINES = [
    '__pycache__/', '*.py[cod]', '*$py.class',
    '*.bak_*', '*.golden',
    'dump_toolbar.py', 'dump_toolbar_out.txt',
    '.watermark_studio/', '*.log',
    'build/', 'dist/', '*.spec',
]

# 1) 删文件（存在就删，删过就跳过）
deleted = 0
for rel in TARGETS:
    p = os.path.join(ROOT, rel)
    if os.path.exists(p):
        try:
            os.remove(p); deleted += 1; print('  删除', rel)
        except Exception as e:
            print('  删 %s 失败：%r' % (rel, e))
print('本轮删除 %d 个文件（之前删过的已跳过）。' % deleted)

# 2) 写 .gitignore
gi = os.path.join(ROOT, '.gitignore')
if not os.path.exists(gi):
    with open(gi, 'w', encoding='utf-8') as f:
        f.write('\n'.join(GITIGNORE_LINES) + '\n')
    print('已创建 .gitignore')
else:
    print('.gitignore 已存在，跳过')

# 3) git add -A —— 关键：把"删除"也暂存进去
r = subprocess.run(['git', 'add', '-A'], capture_output=True, text=True)
print('git add -A:', (r.stdout + r.stderr).strip() or 'ok')

# 4) commit（没有变化也不报错）
r = subprocess.run(['git', 'commit', '-m', 'chore: 清理占位文件与调试残留，新增 .gitignore'],
                   capture_output=True, text=True)
out = (r.stdout + r.stderr).strip()
print('git commit:', out if out else 'ok')
if 'nothing to commit' in out:
    print('（没有新变化可提交——可能删除早已提交，直接 push 即可。）')

print('\n最后一步，你来跑（可能需要登录/验证）：')
print('    git push')
print('push 完告诉我，我再读一次 GitHub 确认。')
