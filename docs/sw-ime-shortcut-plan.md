# SolidWorks 中文输入法下单键快捷键直通 — 实施方案（规划稿）

> 状态：**P1 主链路已实现并验证**（2026-09-10）。P0 探针未产出结论（用户判定交互不可用后直接进入实现），
> 因此 M1 的可行性以真实运行为准；若真机发现 SW 不接受注入消息，回退路径 M2/M0 已在配置里预留。
> 实现位置：`src/sw_key_assist.py`（新增）+ `src/app.py`（接线 3 处）+ 配置/UI/i18n/测试。
> 前置约束：不改动 AutoCAD / 中望 的手势与命令链路（`gesture_engine.py` / `command_executor.py` 保持零改动）。
> 关联历史：`.workbuddy/memory/2026-09-09.md`（V1 智能 IME → 已回退；V2 按焦点切键盘布局 → 保留为 `layout` 模式）

---

## 一、需求与可验收项

原始需求：SolidWorks 画图时，中文输入法下按 `E` 等单键也能正常调用 SW 已绑定的快捷键；不影响其他软件；不影响 SW 中文输入；原有 CAD 逻辑不动。

翻译为 5 条可验收项：

| 编号 | 验收项 | 判定方式 |
|---|---|---|
| A1 | 中文输入法（微信 / 搜狗 / 微软拼音）中文态下，SW 绘图区按单键（E / S / F / 空格）→ SW 执行其当前已绑定的命令 | 用视觉可判定的命令实测（如 `S` = 快捷工具栏） |
| A2 | SW 内所有文本入口（尺寸值、注释文字、特征重命名、文件名、属性框）中文输入不掉字、候选正常、**首字母不被吞** | 逐个入口手打拼音 |
| A3 | 非 SW 前台时键盘行为与未装本工具完全一致 | 记事本 / 浏览器 / VS Code / 微信各输入 1 分钟 |
| A4 | CAD 手势与命令链路零改动、零新增耦合 | `git diff` 仅命中白名单文件 + `pytest tests/ -q` 全绿 |
| A5 | 可一键关闭；关闭即回到现状；工具退出后键盘无任何残留影响 | 设置开关 + 退出后立即连续打字 |

**注意 A1 的措辞**：不要求本工具知道"E 绑定了什么命令"。工具只负责把按键送达 SW，绑定语义完全由 SW 自己的键盘配置决定 —— 这是本方案能天然兼容用户任意自定义快捷键的关键。

---

## 二、根因

中文态下按 `E` 失效，发生在输入链路的**队列层**，早于应用的窗口过程：

```
硬件扫描码 → win32k 按当前布局映射为 VK → 前端线程消息队列
        → 中文输入法（TSF / IMM）在此截获字母键用于开启拼音组合
        → 应用只收到 WM_IME_* 与最终 WM_CHAR，收不到 WM_KEYDOWN
        → SW 的快捷键链路（加速键表 / 自身按键处理）拿不到键 = 命令不触发
```

三点结论：

1. 字母键被"吞"是**输入法在应用之前**做的，应用侧无法自救（所以"在 SW 里调设置"无解）。
2. `SendInput` **不能**绕过：它注入在硬件输入之后、布局映射之前，仍要经过同一套 IME 预处理（业界实测共识）。
3. 微信 / 搜狗 / 百度等第三方输入法的中英态活在各自 TSF 服务里，`WM_IME_CONTROL / IMC_SETCONVERSIONMODE`（IMM 兼容层）对它们无效 —— 这是 09-09 已实证的坑。**因此本方案不依赖"探测输入法是否中文"**，见第六节设计决策 D3。

---

## 三、现状与差距

`src/sw_ime_assist.py`（V2，未提交）用**按焦点切换键盘布局（HKL）**绕开 IME：

- 对任意品牌输入法都有效（因为不碰 IME，直接换键盘布局）；
- 代价：SW 线程被切到 `00000409`，语言栏显示 ENG，绘图区事实上**不再有中文输入法**。

这与 A2 的语义存在张力：用户要的是"输入法保持中文、只是按键能过"，而 V2 是"把输入法从绘图区摘走"。差异虽在体验层面，但正是这次需求的由来。

**决策：保留 V2 作为可选项，主链路换成"不动输入法，只把需要放行的按键直接投给 SW 窗口"。**

---

## 四、机制选型

| 方案 | 原理 | 品牌无关 | 对 SW 中文输入影响 | 对其他软件影响 | 保真度 | 主要风险 |
|---|---|---|---|---|---|---|
| **M1 钩子拦截 + 消息直投**（主线） | `WH_KEYBOARD_LL` 判定命中后吞键，改为 `PostMessage/SendMessage(WM_KEYDOWN/WM_KEYUP)` 直投 SW 窗口 | 是 | **无**（IME 全程不被触碰） | 无（非 SW 前台一律放行） | 中高：合成消息绕过 IME，但不更新应用侧键态 | SW 是否接受注入消息需真机实证（P0 探针） |
| **M2 钩子拦截 + 临时解绑 IME**（备选） | `AttachThreadInput` + `ImmAssociateContext(hwnd, NULL)` → `SendInput` → 还原上下文 | 是 | 瞬时（单键期间无 IME） | 无 | **高**：真实硬件级按键，键态 / 自动重复 / 加速键链路全保真 | 每键两次跨进程 IPC，时序敏感；异常退出可能让 SW 停在"IE 解绑"态 |
| **M0 按焦点切键盘布局**（现状，保留为选项） | `WM_INPUTLANGCHANGEREQUEST` 换 HKL | 是 | 绘图区输入法被摘走（语言栏 ENG） | 无 | 高 | 与 A2 语义张力（见第三节） |
| **M3 user 侧零代码兜底** | 把 SW 常用快捷键改绑 Ctrl / Shift 组合（组合键不进 IME 组合链） | — | 无 | 无 | 高 | 需用户改自己的 SW 配置；单键习惯被打断 |
| **M4 COM `ISldWorks::RunCommand`** | 工具直接调 SW API 执行命令 | 是 | 无 | 无 | **低** | 必须复刻用户 SW 键盘配置（双份维护），且给 CAD 主链路引入 COM 耦合 → **放弃** |

**结论**：主线 M1、回退 M2、保留 M0、放弃 M4、把 M3 写成文档里的用户侧建议。

`ImmAssociateContext(hwnd, NULL)`（M2 的核心）依据微软文档是"移除窗口与输入上下文的关联，因此该窗口无法使用 IME"，是游戏 / 引擎界的惯例做法；跨进程调用需 `AttachThreadInput` 借用目标线程的输入状态，这一点必须真机验证。

---

## 五、P0 探针（先做，决定 M1 是否成立）

**最大不确定性只有一个：SolidWorks 是否接受被直投的键盘消息。** 这必须实测，不能靠推理。

新增 `scripts/sw_key_probe.py`（一次性脚本，不进入发布产物），按序验证：

| 编号 | 验证项 | 判据 |
|---|---|---|
| S1 | `PostMessage(焦点窗, WM_KEYDOWN/UP)` 投 `S` | SW 弹出快捷工具栏（视觉可判定，且无副作用） |
| S2 | 同上，改投 SW 主框架窗 | 同上 |
| S3 | `SendMessageTimeout(..., SMTO_ABORTIFHUNG)` 版本（投递线程执行，不在钩子回调） | 同上 |
| S4 | M2 路径：解绑 IME 上下文后 `SendInput` | 同上 |
| S5 | 文本框中注入是否被误吞 / 干扰候选 | 在 SW 里新建注释打 `ceshi`，候选正常、无掉字 |
| S6 | SW 以管理员运行时 `PostMessage` 返回值 | 返回 0（UIPI 拦截）→ 触发"提权即禁用直通"的设计 |
| S7 | 中文态基线：`Enter / 空格 / Backspace` 在绘图区的真实行为 | 决定键集里要不要包含空格 |
| S8 | `lParam` 正确性对照：`MapVirtualKey` 取扫描码 vs 裸 `1` | 排除"发一次收两次 / F1 变 t"这类经典坑 |
| S9 | **焦点特征观察**：在 SW 里依次点击 图形区 / 尺寸输入框 / 注释编辑 / 特征重命名 | 拿到"绘图区 vs 文本框"的真实 `class` + `caret` 特征矩阵（A2 的地基） |
| S10 | IME 组合态可取性：裸调用 vs `AttachThreadInput` 后 | 决定"正在打拼音"守卫能否成立 |

**已完成的探针实测（09-10 12:30，本机）**：

- `scripts/sw_key_probe.py` 已写出并通过 `--diag` 自检（不投递、只读）。
- **实测结论 1：跨进程 `ImmGetContext` 取不到输入法上下文** —— 裸调用返回 0；补上 `AttachThreadInput` 借用目标线程输入队列后**仍然返回 0**。
  → 直接推论：判定真值表里的"是否正在拼音组合"**不能作为可靠守卫**。已有的 `src/sw_ime_assist.py::_ime_composing()` 也建立在同一假设上（跨进程同样取不到 → 该守卫实际是空转的），模式切到 `layout` 时需一并复核。
  → A2（中文不掉字）的保障重心因此从"组合态"移到**文本控件识别**（控件类名 + caret + 必要时 UIA 复核）。
- **实测结论 2：IMM 兼容层的转换模式仍可跨进程读取**（`WM_IME_CONTROL / IMC_GETCONVERSIONMODE` 返回 `0x0001`，与已知结论一致：能读、但对 TSF 输入法写不动）。可作为**诊断信号**（不是判定条件）。
- 待用户配合的项：S1～S6（投递方式），以及 S9（`--watch` 观察模式）。

命令：

```bash
python scripts/sw_key_probe.py --diag        # 只读诊断，随时可跑
python scripts/sw_key_probe.py --self-test   # 自检交互链路（倒计时 + 置顶弹窗，不投递）
python scripts/sw_key_probe.py --watch --seconds 60   # 在 SW 里点各处，量 class/caret 特征
python scripts/sw_key_probe.py               # 交互式投递测试（核心 5 步）
python scripts/sw_key_probe.py --extended    # 追加 2 个对照步骤
python scripts/sw_key_probe.py --method post_focus    # 只测一个方法
```

**交互通道的设计约束（踩过坑，勿回退）**：被测应用必须占有前台，而"有没有响应"只有人能判定。
若把提示与键盘输入放在命令行，就等于要求用户在 SW 与控制台之间反复手动切换 —— 实操中根本
读不到提示。因此问答通道移出控制台：

- 每步 **5 秒倒计时**（用户只需切一次窗口到 SW），倒计时结束**先校验前台是否为 SLDWORKS**，
  不是就记为"未判定"而不是产出垃圾结论；
- 投递后弹**置顶对话框**（是/否/取消 三个按钮），鼠标点一下即可，无需切窗口、无需键盘；
- 之所以不用"把控制台窗口抢回前台"：Windows Terminal 下 `GetConsoleWindow()` 返回的是隐藏的
  pseudoconsole 窗口，该做法不可靠。

一行一条：`--watch` 的输出也可以直接发我，不必截图。

**成功判据**：S1～S3 中任一通过 → M1 成立，进 P1；全部不通过 → 退 M2（S4）；M2 也不通 → 退 M0，并向用户交付 M3 建议。

探针需在 SW 前台 + 微信输入法中文态下由用户配合操作，脚本只做投递与记录，日志落 `%TEMP%\cad-gesture.log`。

---

## 六、架构（M1 主线）

### 线程模型

```
┌ 主线程(Qt) ────────────────────────────────────────────┐
│ 现有 100ms QTimer  → 按 ime_assist_mode 分发：          │
│    mode=key    → sw_key_assist.probe_context() 发布快照 │
│    mode=layout → sw_ime_assist.run_cycle()   （现状）   │
└───────────────────────┬───────────────────────────────┘
                        │ 不可变快照（命名元组，靠 GIL 原子换引用）
                        ▼
┌ 钩子线程(新增, 自带消息泵) ─────────────────────────────┐
│ WH_KEYBOARD_LL 回调：只做「读快照 + 廉价判定 + 入队」    │
│   命中 → return 1（吞键）+ 投递任务入队                 │
│   未命中 → CallNextHookEx（零干预）                     │
└───────────────────────┬───────────────────────────────┘
                        ▼
┌ 投递线程(新增) ────────────────────────────────────────┐
│ 构造 lParam → PostMessage WM_KEYDOWN/WM_KEYUP 到目标窗  │
│ 失败累计 N 次 → 通知主线程降级（托盘提示）               │
└────────────────────────────────────────────────────────┘
```

**为什么回调里什么重活都不干**：`WH_KEYBOARD_LL` 回调超时会拖慢全球输入，且 Windows 在超时（`LowLevelHooksTimeout`，默认 300ms）后可能**静默移除**该钩子。因此回调内禁止 `OpenProcess` / `SendMessage` / 任何 IPC，只留 `GetForegroundWindow`（廉价、本地）与字典查表。

### 新增模块 `src/sw_key_assist.py`（自包含，不 import CAD 侧任何模块）

| 函数 / 对象 | 纯函数 | 职责 |
|---|---|---|
| `Snapshot`（namedtuple） | — | `sw_hwnd / enabled / text_focus / composing / keyset / elevated_safe` |
| `probe_context()` | 否 | 轮询侧重活：前台进程判定（按 hwnd 缓存 exe，避免每键 `OpenProcess`）、`GetGUIThreadInfo` 取焦点窗与 caret、类名判文本控件、`ImmGetContext` 组合态 |
| `should_intercept(vk, snapshot, fg_hwnd, injected)` | **是** | 唯一决策函数（真值表见第七节），可 100% 单测 |
| `build_key_lparam(vk, is_keyup)` | **是** | 位域拼装：repeat=1 / 扫描码 `MapVirtualKeyW` / 扩展键位 / 前态 / 过渡位 |
| `KeyboardInterceptor.start()/stop()` | 否 | 钩子安装 / 卸载（返回 `c_ssize_t`、`CallNextHookEx` 设 `argtypes`、`GetModuleHandleW(None)` —— 沿用 `gesture_engine` 已验证的写法） |
| `_deliver_loop()` | 否 | 投递线程；失败计数与自动降级 |
| `publish(snapshot)` / `current()` | 否 | 快照发布 / 读取（跨线程唯一共享点） |

### app.py 接线点（仅 3 处）

1. `_init_late`：`_sync_ime_assist_timer()` 之后按模式启动 / 停止拦截器；
2. `_ime_assist_tick()`：由"只跑 layout"改为"按 `ime_assist_mode` 分发"；
3. 配置变更回调（现有 `_sync_ime_assist_timer` 调用处）与退出路径：同步重启 / `stop()` 卸载钩子。

### 设计决策（需确认的三条）

- **D1 不依赖"输入法是否中文"**：微信输入法的中英态无法通过 IMM 读取（已实证），因此判定只基于"SW 前台 + 非文本控件 + 无组合态"，命中即直投。英文态下直投同样正确（键无论如何都该到 SW），代价是极少数使用 `GetKeyState` 的处理路径可能略有差异 —— 列入 P0 探针 S8 的观察项。
- **D2 只吞字母 / 数字 / 空格**，带 Ctrl / Shift / Alt / Win 的组合键一律放行（组合键本来就不进 IME 组合链，无需干预，也避免碰 Shift 这个输入法切换键）。
- **D3 自动重复只放行首次按下**：长按 `S` 不应让 SW 反复开关快捷工具栏，后续 repeat 帧吞掉不投递。

---

## 七、判定真值表（`should_intercept`）

任一条"放行"命中即 `CallNextHookEx`，全不命中才吞键直投：

| 条件 | 结论 | 理由 |
|---|---|---|
| 主开关关闭 / 模式非 key | 放行 | A5 kill switch |
| `injected == True`（`LLKHF_INJECTED`） | **放行** | ① 防自注入回环；② **这是"不动 CAD"的技术保证**：CAD 的 pyautogui 回退注入键绝不能被吞 |
| `vk` 带任何修饰键 | 放行 | 见 D2 |
| `GetForegroundWindow() != snapshot.sw_hwnd` | **放行** | 关闭 100ms 快照的竞态窗口；跨软件误吞的最后一道闸 |
| `snapshot.sw_hwnd == 0`（非 SLDWORKS 前台） | 放行 | A3 |
| `snapshot.composing`（正在打拼音） | 放行 | A2：绝不打断组合（**best-effort**：跨进程读不到，见第五节实测结论 1，不能作为唯一保障） |
| `snapshot.text_focus`（焦点是文本控件） | 放行 | A2：文本框交给输入法 |
| `snapshot.elevated_safe == False`（SW 提权，高于本进程） | 放行 | UIPI 下投递必失败 → 宁可不生效也绝不吞键 |
| `vk not in keyset` | 放行 | 键集可配置 |
| 以上全不命中 | **吞键 + 直投** | A1 |

**文本控件识别**（复用 `sw_ime_assist` 已验证的类名表，不重复造）：`Edit / RichEdit*` 精确匹配 + `combobox / editbox / textbox / inputbox / autocomplete` 后缀匹配（`SWCadEditor` 这类以 editor 结尾的视口类不误判）；**P1 追加 caret 信号**（`GUIThreadInfo.hwndCaret != 0` 说明有文本插入符，绘图区没有），这是防"吞掉拼音首字母"的第二道保险；P2 视实测情况再加 UIA `ControlType == Edit` 复核（跨进程调用慢，只在焦点变化时查一次）。

---

## 八、改动清单（含必须联动处）

| 文件 | 改动 | 风险 |
|---|---|---|
| `src/sw_key_assist.py` | **新增**：钩子 + 快照 + 投递 + 纯函数 | 低（全新模块，无既有引用方） |
| `src/app.py` | 接线 3 处（见第六节） | 中（不得触碰手势链路，改完跑 CAD 回归） |
| `src/config_presets.py` | `settings` 增 `ime_assist_mode`（`key`/`layout`，默认 `key`）、`sw_key_list`（默认 `A-Z,0-9,SPACE`） | 低 |
| `src/config_manager.py` | `_migrate_config` 补两字段（沿用既有"缺字段即补默认"写法） | 低 |
| `src/qt_settings_panel.py` | 「SolidWorks 输入法」区：开关文案更新 + 模式下拉 + 键集编辑 + 帮助文案 | 低 |
| `src/i18n.py` | 新文案中英对照（中文模式 key 即原文） | 低 |
| `tests/test_sw_key_assist.py` | **新增**：真值表全矩阵、`build_key_lparam` 位域、快照跨线程、钩子安装/卸载冒烟 | — |
| `tests/test_settings_panel.py` | 补两个新控件的断言 | — |
| `scripts/sw_key_probe.py` | **新增**：P0 探针（不打包） | — |
| `AGENTS.md` / `CHANGELOG.md` | 新模块说明 + 新坑（回调禁阻塞、`LLKHF_INJECTED` 必须放行） | — |

**禁改（回归底线）**：`src/gesture_engine.py`、`src/command_executor.py`、`src/menu_geometry.py`、`src/qt_radial_menu.py`、`config_manager` 中任何 CAD profile 相关分支。改完以 `git diff --stat` 自证。

---

## 九、风险与对策

| # | 风险 | 对策 |
|---|---|---|
| R1 | **SW 不吃注入消息**（最大不确定） | P0 探针；不成立退 M2；M2 再不通退 M0 + 交付 M3 建议 |
| R2 | 回调阻塞 → 全局输入卡顿 / 钩子被系统静默移除 | 回调只查表入队；异常一律 `CallNextHookEx`；看门狗定期自检 hook 句柄并重装 |
| R3 | 注入事件回环、吞掉 CAD 的 pyautogui 注入键 | 回调首行判 `LLKHF_INJECTED` 直接放行（真值表第 2 行） |
| R4 | 误吞拼音首字母（绘图区与文本框判别错误） | **主保障**：控件类名 + caret 信号（P1 用 S9 实测矩阵定型）；组合态守卫降级为 best-effort（实测跨进程读不到，见第五节）；P2 视情况加 UIA `ControlType` 复核（跨进程慢，只在焦点变化时查一次）；保留托盘"暂停直通"兜底 |
| R5 | 快照 100ms 竞态导致跨软件误吞 | 每键校验 `GetForegroundWindow()` 与快照 hwnd 一致（廉价本地调用） |
| R6 | SW 以管理员运行（UIPI） | 轮询检测完整性级别，高于本进程则关闭直通（不吞键） |
| R7 | 与 Quicker / WGestures / 其他 LL 钩子共存 | 仅在命中条件下吞键，其余全部 `CallNextHookEx`；文档提示钩子链顺序 |
| R8 | 进程被杀 / 崩溃 | 钩子随进程销毁，无残留；M2 模式额外需退出还原 + 看门狗（这也是 M1 优先的原因之一） |
| R9 | SW 多版本 / 多实例 | 判定按 exe 名 + hwnd，天然支持；不做版本特性分支 |

---

## 十、分阶段

| 阶段 | 内容 | 出口条件 |
|---|---|---|
| **P0 探针** | `sw_key_probe.py` + 真机跑 S1～S8 | 确定投递方式（M1 / M2 / M0） |
| **P1 主链路** | `sw_key_assist.py` + app 接线 + 配置/迁移 + 设置页 + 测试 | 真机 A1/A2 通过，`pytest` 全绿 |
| **P2 稳健性** | 看门狗、投递失败自动降级、托盘暂停、提权检测、caret 信号 | A3/A5 + 异常路径（SW 崩溃/退出/最小化）通过 |
| **P3 打磨** | 键集编辑 UI、文案、`AGENTS.md`/`CHANGELOG`、默认值转正 | A4 自证 + 用户确认 |

---

## 十一、真机验证矩阵

| 场景 | 操作 | 期望 |
|---|---|---|
| SW 中文态绘图区 | 按 E / S / F / 空格 | 触发 SW 已绑定命令，语言栏保持中文 |
| SW 文本框内 | 打 `ceshi` 选词 | 候选正常、首字母不掉、无全角空格串入 |
| 拼音组合中 | 按 Esc / 切窗口 | 组合不被打断 |
| 非 SW 前台 | 记事本 / Chrome / VS Code / 微信连续输入 | 与未装工具完全一致 |
| 组合键 | SW 中文态下 Ctrl+Z / Shift 切中英 | 正常 |
| CAD | 跑一次完整手势链路 + `pytest tests/ -q` | 零回归 |
| 开关关闭 | 设置页关闭 → 复测 A1 | 回到现状行为 |
| 工具退出 | 退出后立即连打字母 | 无残留、无延迟 |
| SW 提权运行 | 以管理员启动 SW 后复测 | 不吞键（直通自动禁用） |

---

## 十二、明确不做

- 不改 SW 自身的快捷键配置（不碰 `customui.xml` / `sldreg`）。
- 不引入 SW COM 通道（M4）。
- 不在 SW 里弹本工具的右键圆盘（SW 自带鼠标笔势，09-09 已确认不需要）。
- 不新增全局热键注册（`RegisterHotKey` 会改变其他软件的行为，与 A3 冲突）。
- 不重命名 / 删除 `src/sw_ime_assist.py`（保留为可选模式与回退路径）。

---

## 十三、实现落地记录（P1，2026-09-10）

### 落地文件

| 文件 | 内容 |
|---|---|
| `src/sw_key_assist.py` | **新增**。纯函数（键集解析 / lParam 位域 / 焦点分类 / 判定真值表）+ 轮询采集 `probe_context` + 拦截器 `Interceptor`（钩子线程 / 投递线程 / 自动降级） |
| `src/app.py` | 接线 3 处：`_sync_ime_assist_timer`（按模式启停）、`_sync_sw_interceptor`（装卸钩子）、`_ime_assist_tick`（key 模式发布快照 / layout 模式走旧路径）+ `_quit` 卸载钩子 |
| `src/config_presets.py` / `src/config_manager.py` | 默认值 `ime_assist_mode="key"`、`sw_key_list="A-Z,0-9,SPACE"`、`sw_key_extra_classes=""` + 迁移补字段 |
| `src/qt_settings_panel.py` | TriggerPage 新增：处理方式下拉、直通键集、额外视口类名（layout 模式下自动置灰） |
| `src/i18n.py` | 新文案中英对照（含 4 条 help 长文） |
| `tests/test_sw_key_assist.py` | 17 项：键集解析 / lParam 位域 / 焦点分类 / 判定真值表全守卫 / 快照不可变 / 空窗口投递防护 / 生命周期 |
| `tests/test_settings_panel.py` | +2 项：新控件默认值与置灰联动、refresh 回写 |

### 实现期相对本方案的三处收敛（含理由）

1. **焦点判定改为「正向白名单」**：原方案是「非文本控件即视口」，改为只认
   `AfxFrameOrView* / GXWND / 用户补充类名`，以及「MFC `Afx:` 开头且覆盖框架客户区 ≥50%」。
   理由：两种失败的代价不对称 —— 漏判只是快捷键不生效（等于现状），误判会让用户打不出拼音。
   配套：未识别的类名按 5s 节流记进日志（`[SWKey] 焦点控件未识别…class=xxx`），
   用户可把类名填进 `sw_key_extra_classes` 当场补齐，无需改代码发版。
2. **`Snap.enabled` 语义定为「本快照允许拦截」**（功能开 + 目标前台 + 未被禁用），
   而不是「用户开关开着」。这样钩子回调只需一次布尔判断，也天然让 SW 不在前台时全量放行。
3. **组合键守卫用 `GetAsyncKeyState` 在回调里实时判断**，而不是依赖快照（100ms 粒度会漏掉
   按下修饰键的瞬间）。Shift 也在守卫内 —— 它是输入法中英切换键，绝不能干预。

### 验证

- `py_compile` 全部通过；`scripts/verify.py` 五步全过（含全模块导入检查）。
- `pytest tests/ -q -m "not slow"` → **186 passed**（新增 19 项）。
- 真机冒烟（Python312）：`Interceptor.start()` → `True`，消息泵运行，快照采集正常
  （SW 不在前台时 `enabled=False`、`sw_hwnd=0`，即全量放行），`stop()` 干净卸载。
- 应用已启动（日志出现 `[SWKey] 键盘钩子已安装（SolidWorks 按键直通启用）`）。

### 待用户真机验收（与验证矩阵 A1/A2 对应）

1. SW 图形区 + 中文输入法中文态：按 `E / S / F / 空格` 是否触发 SW 已绑定命令；
2. 若无效：查 `%TEMP%\cad-gesture.log` 有无 `[SWKey] 焦点控件未识别` 或
   `自动停用`；前者把类名填进设置，后者说明 SW 不接受注入（回退 M2/M0）；
3. 文本入口（尺寸值 / 注释 / 重命名）打拼音是否正常、首字母是否被吞；
4. 其他软件与 CAD 手势是否完全无感。
