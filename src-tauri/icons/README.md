# 应用图标

Tauri bundle 需要以下图标（开发期 `tauri dev` 不强制）：

- `32x32.png`
- `128x128.png`
- `128x128@2x.png`
- `icon.icns`（macOS）
- `icon.ico`（Windows）

**推荐做法**：准备一张 1024x1024 的源图（SVG/PNG），运行：

```bash
pnpm tauri icon ./path/to/source.png
```

Tauri 会自动生成所有尺寸到本目录。
