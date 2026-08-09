# ConfigGUI 重构计划

## 问题诊断

### 视觉问题
- 预设命令库横向排列溢出（`pack(side=tk.LEFT)` 7个分类挤在一行）
- 到处是 emoji（🎯✏️💾🗑️），不专业
- 输入框 placeholder 实现粗糙，可能误存
- 圆盘扇区无 hover 反馈，只有点击才高亮
- ttk/tk 混用，样式不统一

### 交互问题
- 两步操作不直观（先选预设 → 再点扇区），状态提示不清晰
- "保存修改"按钮与"保存并关闭"容易混淆
- "交换"功能只能和下一个扇区交换，用途不明
- 预设选中靠 `cget("bg")` 判断，脆弱易出 bug
- 全局 `bind_all("<MouseWheel>")` 影响所有控件

---

## 重构方案

### 1. 圆盘 Hover 高亮

**改动**: `config_gui.py` `_draw_preview()` + 新增 `_on_canvas_motion()`

- 新增状态变量 `_hovered_sector: Optional[Tuple[str, int]]`
- 绑定 `<Motion>` 到 preview_canvas
- 鼠标移动时计算所在扇区，更新 `_hovered_sector`
- 用 `after()` 节流到 16ms（60fps），避免频繁重绘
- `_draw_preview()` 增加 hover 状态绘制（颜色介于默认和选中之间）
- 绑定 `<Leave>` 清除 hover 状态

颜色层次：
- 默认：`inner_sector` / `outer_sector`
- Hover：`inner_sector_hover` / `outer_sector_hover`（新增）
- 选中：`inner_sector_hl` / `outer_sector_hl`

### 2. 预设命令拖放到圆盘

**改动**: `config_gui.py` `_create_preset_button()` + `_on_canvas_click()` → 重构为拖放

流程：
1. 预设按钮绑定 `<ButtonPress-1>` → 创建半透明拖动代理（`Toplevel` + `Label`）
2. 绑定 `<B1-Motion>`（全局）→ 更新代理位置，检测是否在圆盘上方
3. 绑定 `<ButtonRelease-1>`（全局）→ 检测释放位置：
   - 在圆盘扇区内 → 计算扇区索引，将命令写入该扇区
   - 在圆盘外 → 取消拖放
4. 拖放过程中圆盘高亮目标扇区（使用已有的 hover 机制）

实现细节：
- 拖动代理：`Toplevel(overrideredirect=True)`，半透明，跟随鼠标
- 碰撞检测：将全局坐标转换为 canvas 坐标，复用 `_calc_sector_at()` 函数
- 拖放结束后自动刷新右侧编辑面板（如果目标扇区是当前选中扇区）

### 3. 预设命令库重新布局

**改动**: `config_gui.py` `_populate_presets()` + 新增搜索功能

布局改为垂直堆叠：
```
┌─────────────────────────────┐
│ [搜索框: 输入关键词过滤...]    │
├─────────────────────────────┤
│ ▼ 绘图 (21)                  │
│   [直线] [圆] [圆弧] [矩形]  │
│   [多段线] [样条] [椭圆] ...  │
├─────────────────────────────┤
│ ▶ 编辑修改 (20)              │  ← 折叠状态
├─────────────────────────────┤
│ ▶ 标注 (12)                  │
├─────────────────────────────┤
│ ▶ 文字与样式 (10)            │
└─────────────────────────────┘
```

- 每个分类用可折叠 Frame（点击标题展开/折叠）
- 分类标题显示命令数量
- 默认展开第一个分类，其余折叠
- 搜索框实时过滤：输入关键词后，只显示匹配的命令（跨分类）
- 命令按钮改为更紧凑的网格布局（4列）

### 4. 扇区编辑面板优化

**改动**: `config_gui.py` 编辑面板部分

- 移除"保存修改"按钮，改为**自动保存**：编辑框内容变化时自动写入内存
  - 用 `trace_add("write", ...)` 监听 StringVar 变化
  - 变化后立即更新 config 字典 + 重绘圆盘预览
- 移除"交换"按钮（用途不明确，用户反馈差）
- 保留"清空"按钮
- 编辑面板增加视觉反馈：有内容的编辑框左边显示绿色竖线

### 5. 圆盘交互增强

**改动**: `config_gui.py` `_on_canvas_click()` + 新增 canvas 绑定

- 点击扇区 → 选中并在右侧面板显示详情（保留现有逻辑）
- 双击扇区 → 聚焦到右侧编辑面板的第一个输入框
- 鼠标样式：hover 到可点击扇区时显示 `hand2` 光标
- 移除 center 死区的"释放"文字，改为显示当前选中扇区的 label（与实际圆盘一致）

### 6. 视觉细节打磨

**改动**: `config_gui.py` COLORS + `_setup_styles()`

- 去掉所有 label 中的 emoji 前缀，改为纯文字或使用 unicode 符号（如 ▶ ● ■）
- 新增 hover 颜色变量：
  ```python
  "inner_sector_hover": "#4a4a80",
  "outer_sector_hover": "#353560",
  ```
- 预设命令按钮 hover 效果改为 ttk.Style 统一管理
- Profile 树的活跃标记从 `▶` 前缀改为 tag 配色（加粗 + accent 色）

### 7. 键盘与滚动修复

**改动**: `config_gui.py`

- 移除 `bind_all("<MouseWheel>")`，改为只在预设命令区域绑定
- 添加快捷键：
  - `Escape`：取消当前拖放操作
  - `Ctrl+S`：保存并关闭
- 预设命令区域支持键盘上下左右导航

---

## 不改动的部分

- `_InputDialog` 和 `_TargetDialog` 辅助类（功能正常）
- Profile 增删改逻辑（交互合理）
- `config_manager.py`（不需要改）
- `radial_menu.py`（只改配置界面，不影响运行时圆盘）
- 底部"重置默认"和"保存并关闭"按钮（保留）

---

## 文件改动范围

| 文件 | 改动程度 | 说明 |
|------|----------|------|
| `src/config_gui.py` | 大幅重构 | 主要改动文件 |
| `src/config_manager.py` | 不改 | — |
| `src/radial_menu.py` | 不改 | — |
| `src/gesture_engine.py` | 不改 | — |

---

## 实施顺序

1. 先加 hover 高亮（独立功能，不影响其他逻辑）
2. 重构预设命令库布局（垂直 + 搜索）
3. 实现拖放功能
4. 优化编辑面板（自动保存、移除交换）
5. 视觉细节打磨
6. 键盘与滚动修复
7. 整体测试验证

---

## 验证方式

```bash
python main.py
```

手动测试：
- [ ] 圆盘 hover 高亮正常
- [ ] 拖放预设命令到扇区正常
- [ ] 搜索过滤正常
- [ ] 编辑面板自动保存正常
- [ ] Profile 切换正常
- [ ] 保存/重置正常
- [ ] 无 emoji 显示
- [ ] 滚轮只在预设区域生效
