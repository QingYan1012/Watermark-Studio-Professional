# -*- coding: utf-8 -*-
"""
生成 水印标注工坊 (Watermark Studio) 高清精美应用图标 app.ico
具备阴影、透视四边形网格、发光多锚点与紫罗兰徽章
"""

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def generate_pro_icon(output_path="app.ico"):
  size = (256, 256)
  img = Image.new("RGBA", size, (0, 0, 0, 0))

  # 1. 底层高斯模糊弥散阴影
  shadow = Image.new("RGBA", size, (0, 0, 0, 0))
  sdraw = ImageDraw.Draw(shadow)
  sdraw.rounded_rectangle(
      [18, 22, 238, 242], radius=44, fill=(0, 0, 0, 140)
  )
  shadow = shadow.filter(ImageFilter.GaussianBlur(12))
  img.paste(shadow, (0, 0), shadow)

  # 2. 软件圆角外框（深色极客风底座）
  draw = ImageDraw.Draw(img)
  base_box = [16, 16, 240, 240]
  draw.rounded_rectangle(
      base_box, radius=42, fill="#181a20", outline="#2b5b84", width=3
  )
  draw.rounded_rectangle(
      [20, 20, 236, 236], radius=38, fill=None, outline="#3ea6ff", width=2
  )

  # 3. 倾斜透视四边形区域（代表透视矫正与照片）
  p_pts = [(45, 65), (210, 50), (200, 185), (55, 175)]
  draw.polygon(p_pts, fill=(35, 75, 110, 220), outline="#5294e2")

  # 内部地质网格导向线
  draw.line([(48, 120), (205, 118)], fill="#3ea6ff", width=2)
  draw.line([(128, 58), (128, 180)], fill="#3ea6ff", width=2)

  # 4. 多锚点绘制（4 个发光金黄色角点 + 4 个边中点）
  for px, py in p_pts:
    draw.ellipse([px - 10, py - 10, px + 10, py + 10], fill=(255, 179, 71, 100))
    draw.ellipse(
        [px - 6, py - 6, px + 6, py + 6],
        fill="#ffb347",
        outline="#ffffff",
        width=2,
    )

  mid_pts = [
      ((45 + 210) // 2, (65 + 50) // 2),
      ((210 + 200) // 2, (50 + 185) // 2),
      ((200 + 55) // 2, (185 + 175) // 2),
      ((55 + 45) // 2, (175 + 65) // 2),
  ]
  for mx, my in mid_pts:
    draw.rectangle(
        [mx - 4, my - 4, mx + 4, my + 4],
        fill="#3ea6ff",
        outline="#ffffff",
        width=1,
    )

  # 5. 右下角紫罗兰色 WM 水印微章
  badge_box = [115, 152, 228, 218]
  draw.rounded_rectangle(
      badge_box, radius=14, fill="#7b42bc", outline="#ffffff", width=2
  )
  draw.rounded_rectangle(
      [117, 154, 226, 216], radius=12, fill=None, outline="#b883ff", width=1
  )

  try:
    font = ImageFont.truetype("arialbd.ttf", 34)
  except Exception:
    font = ImageFont.load_default()

  draw.text((172, 184), "WM", font=font, fill="#ffffff", anchor="mm")

  # 导出多分辨率 Windows ICO
  icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
  img.save(output_path, format="ICO", sizes=icon_sizes)
  print(f"✨ 高颜值图标已生成：{output_path}")


if __name__ == "__main__":
  generate_pro_icon()