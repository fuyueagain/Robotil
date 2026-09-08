# Learn.md — 问题记录与解决方案

> 本文件记录开发过程中遇到的环境/脚本问题、根因与解决方案，便于后续快速排查。

---

## 科普：`general_motion_retargeting/params.py` 的四个关键字典（小白版）

> 这个模块做的是“动作重定向（Motion Retargeting）”：把人体的动作 / 各种动捕数据，转成机器人能用的关节动作。
> `params.py` 里几乎没有计算逻辑，只有 4 张“对照表”（Python 叫字典 dict），本文用大白话讲清楚每张表是干什么的。

### 0. 先搞懂“字典 dict”
字典就像手机通讯录：`名字 → 电话号码`。代码里写作 `{'名字': '内容'}`。
查表用 `表名['名字']`，查不到会报 `KeyError`。

### 四张表总览（先看这张就懂了大半）
| 字典名 | 大白话 | 比方 | 存的到底是什么 |
| --- | --- | --- | --- |
| `ROBOT_XML_DICT` | 机器人代号 → 机器人模型文件 | “名字 → 全身照” | 每个机器人对应哪个 MuJoCo XML 模型 |
| `IK_CONFIG_DICT` | 动作来源 → 机器人 → 翻译说明书 | “外语 → 机器人语 词典” | 不同来源的动作数据怎么映射到机器人的 IK 配置 |
| `ROBOT_BASE_DICT` | 机器人 → 它的“腰/根节点” | “先找腰，动作才挂得住” | 每个机器人根节点（base link）的名字 |
| `VIEWER_CAM_DISTANCE_DICT` | 机器人 → 预览相机距离 | “看表演站多远” | viewer 里默认相机距离 |

### ① `ROBOT_XML_DICT` —— 机器人“身体文件”放哪
记的是：**机器人代号 → 模型文件路径**。例如：
```python
ROBOT_XML_DICT = {
    'unitree_g1': ASSET_ROOT / 'unitree_g1' / 'g1_mocap_29dof.xml',  # 宇树 G1
    'unitree_h1': ASSET_ROOT / 'unitree_h1' / 'h1.xml',              # 宇树 H1
    ...
}
```
- 类比：上台前要给每个“演员”找到它的身体模型；要用哪个机器人，先按代号来这里查模型文件。
- 小白注意：路径用 `/` 拼接（跨平台，不写死盘符）；文件是 MuJoCo 用的 XML/MJCF。

### ② `IK_CONFIG_DICT` —— 动作“翻译说明书”（唯一的两层表）
先按“动作从哪来”分大类（第一层 key），再按“给哪个机器人”分小类（第二层 key），最里层才是配置文件路径：
```python
IK_CONFIG_DICT = {
    'smplx': {   # 第一层：动作来源 = SMPL-X 人体模型/动捕
        'unitree_g1': IK_CONFIG_ROOT / 'smplx_to_g1.json',   # 第二层：目标机器人
        'unitree_h1': IK_CONFIG_ROOT / 'smplx_to_h1.json',
        ...
    },
    'bvh_lafan1': { ... },   # 另一种来源：BVH 动捕数据
    ...
}
```
- 类比：人和机器人“骨骼”不一样。同样是“抬右手”，关节怎么对应、偏移多少，都写在这本“词典”（json）里，程序再用 IK（逆向运动学）算出每个关节该转多少度。
- 目前有 8 种动作来源：`smplx`、`bvh_lafan1`、`bvh_nokov`、`bvh_xsens`、`fbx`、`fbx_offline`、`xrobot`、`xsens_mvn`。
- 小白注意：**不是每种动作来源都支持所有机器人**（比如 `pal_talos` 只在 `bvh_lafan1` 里有）；配了才查得到。

### ③ `ROBOT_BASE_DICT` —— 机器人的“腰”（根节点）
记的是：**机器人 → 根节点 link 叫什么**。例如 `'unitree_g1': 'pelvis'`、`'booster_t1': 'Waist'`、`'engineai_pm01': 'LINK_BASE'`。
- 类比：人走路、转身是“腰/盆骨”带动的。做重定向要先告诉程序“这台机器人的腰是哪一节”，位移和重心才能正确挂上去。
- 小白注意：各家模型的根节点命名五花八门（`pelvis` / `Waist` / `base_link` / `imu_2`…），**不能猜，必须查这张表**。

### ④ `VIEWER_CAM_DISTANCE_DICT` —— 预览时相机站多远
记的是：**机器人 → 相机距离（米）**。例如 `'unitree_h1': 3.0`（大个子站远点）、`'stanford_toddy': 1.0`（小机器人走近点）。
- 只影响“看效果”的 viewer 画面，不影响动作数据本身。

### 四张表怎么配套用（伪代码）
```python
model = ROBOT_XML_DICT[robot]                        # ① 取身体模型
root  = ROBOT_BASE_DICT[robot]                       # ③ 找“腰”（根节点）
cfg   = IK_CONFIG_DICT[motion_source][robot]         # ② 拿翻译说明书
cam   = VIEWER_CAM_DISTANCE_DICT.get(robot, 2.0)     # ④ 相机站多远（缺省 2 米）
```
### 新增一台机器人要记得
前三张表（XML / base / 相机）的机器人代号**一一对应**（目前都是 22 个），加机器人时要同步补：模型路径、根节点名、相机距离，以及 `IK_CONFIG_DICT` 里需要的动作翻译配置，否则重定向会查不到而报错。

---

## 问题 1：run_test.bat 中 conda 虚拟环境激活路径错误

### 错误现象
`run_test.bat` 使用 `call D:\anaconda\Scripts\activate.bat wham_gmr` 激活环境，但本机 `D:\anaconda` 目录不存在，导致激活脚本找不到、环境无法正确激活。

### 本机环境事实
| 检查项 | 路径 | 是否存在 |
| --- | --- | --- |
| conda 根目录 | `D:\Miniconda`（`D:\Miniconda\Scripts\conda.exe`） | ✅ |
| conda 激活脚本 | `D:\Miniconda\Scripts\activate.bat` | ✅ |
| wham_gmr 环境 | `D:\Miniconda_env\envs\wham_gmr\python.exe` | ✅ |
| 环境目录配置 | `C:\Users\yay\.condarc` → `envs_dirs: [D:\Miniconda_env\envs]` | ✅ |

### 解决方案
将 `run_test.bat` 中 activate.bat 路径改为 conda 根目录下的实际路径：
```bat
call D:\Miniconda\Scripts\activate.bat wham_gmr
```
> 注意：conda 4.6+ 的激活脚本统一位于 conda 根目录 `Scripts\` 下，环境目录内（`envs\wham_gmr\Scripts\activate.bat`）不再自带激活脚本。

---

## 问题 2：运行 run_test.bat 报 "WHAM_PYTHON cannot import 'smplx'"

### 错误信息（完整）
```
[E2E] Python selection: WHAM_ENV=wham_gmr GMR_ENV=wham_gmr CONDA_PREFIX=D:\miniconda WHAM_PYTHON=D:\miniconda\python.exe GMR_PYTHON=D:\miniconda\python.exe
D:\Robot-imitation-learning\run.ps1 : [E2E] Selected WHAM_PYTHON cannot import 'smplx': D:\miniconda\python.exe. Expected a Python from conda env 'wham_gmr', e.g. 'C:\Users\yay\.conda\envs\wham_gmr\python.exe'.
At D:\Robot-imitation-learning\run.ps1:230 char:5
```

### 根因分析（诊断链）
| 步骤 | 现象 | 结论 |
| --- | --- | --- |
| 1 | bat 内 `call activate.bat wham_gmr` 后 `CONDA_PREFIX` 正常为 wham_gmr | activate.bat 本身无问题 |
| 2 | `powershell -File run.ps1` 启动的子进程中 `CONDA_PREFIX` 变回 base | **新 PowerShell 加载了 profile** |
| 3 | profile 中 conda init hook 执行 `conda activate 'base'` | conda 配置 `auto_activate: True`（由 `conda config --show auto_activate_base` 确认） |
| 4 | `run.ps1` 按 `$env:CONDA_PREFIX` 推断 Python，选到 base 的 `D:\miniconda\python.exe` | base 环境未安装 `smplx` → 报错 |
| 5 | 环境实际在 `D:\Miniconda_env\envs\wham_gmr`（`.condarc` 的 `envs_dirs` 指定） | `run.ps1` 默认候选列表（`<root>\envs\...`）找不到 |

**一句话根因**：PowerShell 每次启动都会通过 profile 里的 conda hook 强制激活 base，把 `run_test.bat` 里 activate 好的 `wham_gmr` 环境覆盖掉了，导致 `run.ps1` 按错误的 `CONDA_PREFIX` 选了 base 的 Python。

### 解决方案

#### 修改 1：run_test.bat —— PowerShell 子进程跳过 profile
```bat
:: 修改前
powershell -ExecutionPolicy Bypass -File run.ps1
:: 修改后
powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1
```
`-NoProfile` 使新 PowerShell 不加载 profile，conda hook 不会执行，从而继承 cmd 中激活好的 `wham_gmr` 环境。

#### 修改 2：run.ps1 —— 环境查找支持自定义 envs_dirs（防御性）
`Get-CondaEnvPythonCandidates` 函数增强：从 `CONDA_ENVS_PATH` 环境变量和 `~/.condarc` / `$CONDARC` / `$APPDATA\conda\.condarc` 解析 `envs_dirs`，将这些目录也加入候选，使 `CONDA_PREFIX` 指向 base 时仍能找到 `wham_gmr` 的 Python。

### 验证结果
| 场景 | CONDA_PREFIX | WHAM_PYTHON | 结果 |
| --- | --- | --- | --- |
| base 未激活直接运行 `run_test.bat` | `D:\Miniconda_env\envs\wham_gmr` ✅ | `...\wham_gmr\python.exe` ✅ | 环境验证通过 |
| 已激活 `(wham_gmr)` 的 PowerShell 运行 | `D:\Miniconda_env\envs\wham_gmr` ✅ | `...\wham_gmr\python.exe` ✅ | 环境验证通过 |
| 其他入口（CONDA_PREFIX=base 直接跑 `run.ps1`） | `D:\miniconda` | `...\wham_gmr\python.exe` ✅ | 环境验证通过 |

> 验证方式：设置 `E2E_VALIDATE_ENV_ONLY=1` 后运行，脚本仅做环境校验（能 import `smplx`）即退出，不会触发完整视频处理流程。

---

## 关键经验（下次直接复用）

1. **PowerShell 启动会执行 profile 里的 conda init hook**，若 conda 配置 `auto_activate`（旧名 `auto_activate_base`）为 True，会强制激活 base，覆盖已激活环境。
   - 排查命令：`conda config --show auto_activate_base`
   - 规避手段：脚本内启动 PowerShell 一律加 `-NoProfile`
2. **conda 环境可能不在默认 `<root>\envs\` 下**，而是通过 `.condarc` 的 `envs_dirs` 自定义位置。
   - 排查命令：`conda env list`（看环境实际路径）
   - 脚本处理：从 `CONDA_ENVS_PATH` / `.condarc` 的 `envs_dirs` 读取环境目录
3. **`cmd /c "..."` 中 `%VAR%` 在 cmd 启动时即展开**（用的是启动前的环境值），调试脚本内变量时应在 **bat 内部逐行 echo**，否则会看到过期假象。
4. **调试 cmd 激活链路时注意 `SETLOCAL/ENDLOCAL` 与括号块的变量展开时机**：括号块内 `%VAR%` 是解析时展开，`FOR` 变量（`%%A`）是执行时展开；需要真实值时在括号块外输出或用 `CALL echo %%VAR%%` 二次展开。

---

## 问题 3：运行 run_test.bat 报 Permission denied + 视频文件损坏

### 错误信息（完整）
```
ERROR | _gmr_worker_loop - [GMR] worker error robot=unitree_g1 frame=0: [Errno 13] Permission denied: 'output/test_run/csv\\unitree_g1\\retarget_metadata.json.tmp'
无法打开视频D:\Robot-imitation-learning\output\test_run\video\live_stream_robot.mp4
```
视频 ffprobe 检查：`moov atom not found`（录制未正常收尾，文件损坏）。

### 根因分析（两个独立问题）
| # | 问题 | 根因 |
| --- | --- | --- |
| 1 | `retarget_metadata.json.tmp` 写入 Permission denied | `init_gmr_state()` 会被 **主线程（1966 行）和 GMR worker 线程（1725 行）并发调用**；当 `state["retarget"]` 为 None 时两线程同时进入初始化分支，`_write_unity_qpos_metadata()` 的 `metadata_written` 检查是 check-then-act（无锁），两线程并发写同一 `.tmp` 文件 → Windows 上一个成功、一个报 Errno 13 |
| 2 | 视频损坏（moov 缺失）+ 程序收尾卡住 | 无显示器环境（`DISPLAY` 为空 → headless）下，代码仍用 `RobotMotionViewer`（依赖 GLFW 窗口）录制视频：离屏渲染中途失败导致视频停止；收尾 `viewer.close()`（GLFW close）挂起 → `mp4_writer.close()` 永不执行 → moov 不写入 |

### 解决方案
#### 修改 1：handle_wham_gmr.py —— metadata 写入加线程锁
`_write_unity_qpos_metadata()` 增加模块级 `threading.Lock`，锁内 double-check `metadata_written`：
```python
_metadata_write_lock = threading.Lock()
def _write_unity_qpos_metadata(state):
    ...
    with _metadata_write_lock:
        if state.get("metadata_written"):
            return
        ...  # 原有写入逻辑
```

#### 修改 2：handle_wham_gmr.py —— headless 环境用离屏渲染录制视频
- `_HeadlessViewer` 增加 `record_video / video_path / video_width / video_height` 参数，用 `mj.Renderer` 离屏渲染 + `imageio` writer 录视频（不依赖 GLFW），`close()` 正常关闭 writer（写入 moov）。
- 两处 viewer 创建逻辑：`_is_headless` 为真时**一律用 `_HeadlessViewer`**（包括录制视频），不再回退到 `RobotMotionViewer`。

### 验证结果（完整流程 run_test.bat，退出码 0）
| 产物 | 结果 |
| --- | --- |
| `retarget_metadata.json` | 只写入一次（锁生效），无 Permission denied |
| `live_motion.csv` | 654 行正常写入 |
| `my_motion.pkl` / `gmr_smplx_results.npz` | 正常生成 |
| `live_stream_robot.mp4` | **有效视频**：h264、304x544、641 帧、21.37s、moov 正常 |

### 关键经验补充
5. **多线程共享 state 的"检查再写入"必须加锁**（check-then-act 竞态），Python 中即使有 GIL，跨线程的文件写/替换仍可能冲突（Windows 上表现为 `Permission denied` / `Sharing violation`）。
6. **headless（无 DISPLAY）环境不要用依赖 GLFW 窗口的 viewer 录视频**：GLFW 创建/关闭窗口可能失败或挂起。应使用 `mj.Renderer` 离屏渲染（可配 `MUJOCO_GL=egl` / osmesa 软件渲染）。
7. **MP4 的 moov atom 只在 writer.close() 时写入**：程序异常退出/挂起 → 视频文件无 moov → 任何播放器都打不开。排查时用 ffprobe：`ffprobe -v error -show_entries format=duration file.mp4`。

---

## 问题 4：Python 字符串中 Windows 反斜杠路径的转义陷阱

### 错误现象
`convert_urdf_to_mjcf.py` 中写：
```python
urdf_path = 'D:\Robot-imitation-learning\assets\LingLong2.0/LingLong2.0.urdf'
```
运行后报文件找不到/路径损坏。用 `repr()` 检查发现路径实际变成了：
```python
'D:\\Robot-imitation-learning\x07ssets\\LingLong2.0/LingLong2.0.urdf'
```

### 根因分析
| 项目 | 说明 |
| --- | --- |
| 触发原因 | Windows 反斜杠路径写在 Python **普通字符串**（`'...'` / `"..."`）中，`\` 是转义前缀 |
| `\a` → 响铃符 `\x07` | `...\assets\...` 中的 `\a` 被转义，路径被破坏（`assets` → `\x07ssets`） |
| `\t` `\n` `\r` 等 | 同样会被转义成制表符/换行/回车 |
| `\R` `\L` 等 | 无效转义：Python 保留反斜杠，但会触发 `SyntaxWarning` |
| 代码内部 | `open()` / `os.path` / MuJoCo 本身跨平台（`/` 与 `\` 都识别），问题只出在**硬编码字符串的写法** |

### 解决方案（三种安全写法）
```python
# ① 正斜杠（推荐：Windows 与 Linux 通用，无需转义）
urdf_path = 'D:/Robot-imitation-learning/assets/LingLong2.0/LingLong2.0.urdf'

# ② 原始字符串（保留反斜杠，仅 Windows 习惯）
urdf_path = r'D:\Robot-imitation-learning\assets\LingLong2.0\LingLong2.0.urdf'

# ③ 反斜杠转义（每个 \ 写成 \\）
urdf_path = 'D:\\Robot-imitation-learning\\assets\\LingLong2.0\\LingLong2.0.urdf'
```
> 跨平台 / 换机建议用相对路径 + `os.path.join`：
> ```python
> import os
> urdf_path = os.path.join('assets', 'LingLong2.0', 'LingLong2.0.urdf')
> ```

### 验证结果
| 检查项 | 结果 |
| --- | --- |
| 语法检查 | 通过 ✅ |
| 运行转换 | `✅ 转换成功！nq= 30 nu= 0` ✅ |
| 输出 XML | `assets/LingLong2.0/LingLong2.0.xml`（21727 字节）正常生成 ✅ |
| 临时文件 | `_tmp_*.urdf` 自动清理无残留 ✅ |

### 关键经验补充
8. **在 Python 普通字符串中写 Windows 路径必须用正斜杠 / 原始字符串 `r'...'` / 转义 `\\`**；`\a`、`\t`、`\n`、`\r`、`\b`、`\f`、`\v` 是合法转义会静默破坏路径，`\R`、`\L` 等无效转义会触发 `SyntaxWarning`。
9. **排查"文件明明存在却打不开"时**，先用 `print(repr(路径变量))` 看字符串真实内容，确认是否被转义污染（例如出现 `\x07`、`\t`、`\n` 等控制字符）。

---

## 问题 5：URDF → MJCF 转换（convert_urdf_to_mjcf.py）与教程的差异点

> 教程（LingLong2.0 部署指南 2.1 / 2.2）基于作者的环境，实际转换时发现若干"教程写法对不上实际文件"的点，全部已脚本化处理。

### 差异点汇总（教程 vs 实际）

| # | 教程写法/期望 | 实际遇到 | 根因 |
| --- | --- | --- | --- |
| 1 | 教程 2.1 期望 `nu=30` | 首次转换 `nu=0` | MuJoCo 从 URDF 导入**默认不生成 actuator**，MJCF 无 `<actuator>` 块 |
| 2 | 教程 2.2 ① 让"找到 `<body name="base_link" ...>` 手工改" | **XML 里根本没有 `base_link` 的 `<body>`** | URDF 中 `base_link` 经 **fixed 关节**（`world_base_joint`）连 world，**mujoco>=3 编译时折叠 fixed 关节**，base_link 只剩 mesh `<geom>` 挂在 `<worldbody>` 下 |
| 3 | 教程 2.2 ② 让"找到 `<joint name="xxx_yaw" type="hinge" ...>`" | 按此写法搜不到 | MJCF 关节名带 `_joint` 后缀（`waist_yaw_joint`），且 MuJoCo 默认 hinge 关节**不写 `type="hinge"`** |
| 4 | 教程 2.2 ① freejoint 写法 `<freejoint name="base_free"/>` | 脚本生成 `<freejoint name="base_free" />` | 有无空格 XML 等价，无影响（仅记录） |
| 5 | 教程假定 mujoco 行为 | `mjtJoint` 枚举**无 `mjJNT_FIXED`** | 本机 mujoco **3.12.0**：fixed 关节编译时折叠，模型里不存在 fixed joint |

### 解决方案（convert_urdf_to_mjcf.py 已自动化，一条命令完成）

```python
python convert_urdf_to_mjcf.py
```

| 脚本步骤 | 自动完成内容 | 对应指南 |
| --- | --- | --- |
| 第 5 步 | 遍历非固定关节，为每个补 `<motor joint="..."/>`（`nu` 0→30） | 2.1 |
| 第 6 步 | XML 重构（ElementTree）：把被折叠的 base 提升为 `<body name="base_link" pos="0 0 0.9"><freejoint name="base_free"/></body>`，全部机器人 body 移入其下（`nq` 30→37） | 2.2 ① |
| 第 7 步 | 用**负向前瞻正则**给 6 个缺 axis 的 yaw 关节补 `axis="0 0 1"`（已有 axis 不重复加） | 2.2 ② |

运行输出：
```
✅ 已为 30 个运动关节添加 motor actuator
✅ 已为 base_link 补浮动基座 freejoint（nq 将 +7）
✅ 已为 6 个缺 axis 的 yaw 关节补 axis="0 0 1"
✅ 转换成功！nq= 37 nu= 30
```

### 验证结果
| 检查项 | 结果 |
| --- | --- |
| mujoco 版本 | 3.12.0（wham_gmr 环境） |
| `nq` / `nu` | 37 / 30 |
| `base_free` freejoint | 存在，仿真 `mj_step` 正常 |
| 6 个 yaw 关节内部 axis | 均为 `[0.0, 0.0, 1.0]` |
| 重复运行幂等性 | 负向前瞻保证已补的 axis/freejoint 不会重复添加（freejoint 逻辑判断 `<actuator>`/body 存在跳过） |

### 关键经验补充
10. **MuJoCo>=3 从 URDF 导入会自动折叠 fixed 关节**：fixed 链（`world → base_link` 等）不再生成独立 body，mesh 以 `<geom>` 形式提升到父级。判断关节是否 fixed 时不要用 `mjtJoint.mjJNT_FIXED`（3.x 已移除该枚举），用 `getattr(mujoco.mjtJoint, "mjJNT_FIXED", None)` 兼容，或直接认为"模型里只剩运动关节"。
11. **MuJoCo URDF 导入不生成 actuator**：`nu`（执行器数）默认为 0；需要驱动时必须手动/脚本为每个运动关节补 `<motor joint="..."/>`。
12. **MJCF 与 URDF 的关节写法不同**：MJCF 关节名通常带 `_joint` 后缀、hinge 关节默认不写 `type`；按教程里的 URDF 写法（`type="hinge"`）在 MJCF 里搜不到属正常现象，应以实际 `name` 为准。
13. **“手工修正”应优先脚本化**：把教程的手工步骤（补 actuator / 浮动基座 / yaw axis）写成可重复脚本，避免每次转换重复劳动，且用**负向前瞻正则**保证幂等（重复执行不重复修改）。

---

## 工具：`grep`、`ripgrep`（`rg`）与 `find`

这三个命令都用于“找东西”，但查找对象不同：

| 命令 | 主要查找对象 | 默认行为 | 典型用途 |
| --- | --- | --- | --- |
| `grep` | 文件内容 | 只搜索传入的文件；递归需加 `-r`/`-R` | Linux/Unix 基础文本搜索 |
| `rg`（ripgrep） | 文件内容 | 默认递归搜索当前目录，并遵循 `.gitignore` | 代码项目中的快速搜索 |
| `find` | 文件和目录属性 | 从指定目录递归遍历 | 按名称、类型、大小、时间查找文件 |

### 系统支持

| 系统 | `grep` | `rg`（ripgrep） | `find` |
| --- | --- | --- | --- |
| Linux | 通常默认安装 | 通常需安装 | 通常默认安装 |
| macOS | 通常默认安装 | 可用 Homebrew 安装 | 通常默认安装 |
| Windows PowerShell | 可通过 WSL/Git Bash 使用 | 安装后可直接使用 | 用 `Get-ChildItem` 替代更自然 |
| Windows CMD | 可用相近的 `findstr` | 安装后可使用 | 没有原生 GNU `find` |

安装 ripgrep 的示例：

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ripgrep

# macOS
brew install ripgrep

# Windows（winget）
winget install BurntSushi.ripgrep.MSVC
```

### `grep`：搜索文件内容

```bash
# 搜索一个文件
grep "learning_rate" config.py

# 递归搜索当前项目，并显示行号
grep -rn "batch_size" .

# 忽略大小写、只搜索 Python 文件
grep -rni --include="*.py" "warning" .

# 只显示匹配的文件名
grep -rl "TODO" .

# 显示匹配行前后各 3 行
grep -nC 3 "Traceback" app.log

# 搜索多个关键词（扩展正则中的“或者”）
grep -rnE "TODO|FIXME" src/
```

常用选项：

| 选项 | 含义 |
| --- | --- |
| `-n` | 显示行号 |
| `-i` | 忽略大小写 |
| `-r`/`-R` | 递归搜索目录 |
| `-l` | 只显示匹配的文件名 |
| `-v` | 显示不匹配的行 |
| `-w` | 按完整单词匹配 |
| `-F` | 按普通字符串匹配，不解析正则 |
| `-E` | 使用扩展正则表达式 |
| `-C N` | 显示上下文各 `N` 行 |
| `--include` | 递归时只包含指定文件 |
| `--exclude-dir` | 排除目录 |

### `rg`（ripgrep）：更适合代码项目

`rg` 的基本用法：

```bash
# 默认递归搜索当前目录
rg -n "learning_rate"

# 只搜索 Python 文件
rg -n -g "*.py" "batch_size" .

# 查找定义和调用的常见文本形式
rg -n "^\\s*def\\s+train_model" .
rg -n "train_model\\s*\\(" .

# 查找赋值定义，并显示上下文
rg -n -C 5 "batch_size\\s*=" .

# 查找多个关键词，只显示文件名
rg -l "TODO|FIXME" .

# 列出项目中的 Python 文件
rg --files -g "*.py"
```

常用选项：

| 选项 | 含义 |
| --- | --- |
| `-n` | 显示行号 |
| `-i` | 忽略大小写 |
| `-l` | 只显示文件名 |
| `-C N` | 显示上下文各 `N` 行 |
| `-g "模式"` | 用 glob 限定文件，如 `*.py` |
| `-g "!模式"` | 排除匹配的文件或目录 |
| `--hidden` | 包含隐藏文件 |
| `--no-ignore` | 忽略 `.gitignore`，搜索所有文件 |
| `-F` | 按普通字符串匹配 |
| `-w` | 按完整单词匹配 |
| `--files` | 列出可搜索的文件名 |

常见正则：

| 表达式 | 含义 |
| --- | --- |
| `\\s*` | 任意数量的空白字符 |
| `\\s+` | 至少一个空白字符 |
| `\\(` | 字面量左括号 |
| `^` / `$` | 行首 / 行尾 |
| `A|B` | 匹配 A 或 B |

`rg` 默认跳过 `.git`、`.gitignore` 排除路径和常见二进制文件；需要搜索这些内容时才使用 `--hidden` 或 `--no-ignore`。

### `find`：按文件名和属性查找

```bash
# 按名称查找
find . -name "*.py"
find . -iname "*train*"       # 不区分大小写

# 按类型查找
find . -type f                 # 普通文件
find . -type d                 # 目录

# 按大小、修改时间查找
find . -type f -size +100M
find . -type f -name "*.py" -mtime -7

# 限制遍历层数、按路径筛选
find . -maxdepth 2 -name "*.py"
find . -path "*/tests/*" -name "*.py"
```

常用条件：

| 条件 | 含义 |
| --- | --- |
| `-name` / `-iname` | 按名称匹配（区分/不区分大小写） |
| `-type f` / `-type d` | 普通文件 / 目录 |
| `-size +100M` | 大于 100 MB |
| `-mtime -7` | 最近 7 天修改过 |
| `-empty` | 空文件或空目录 |
| `-maxdepth N` | 最多遍历 `N` 层 |
| `-path` | 按完整路径匹配 |

把 `find` 的结果交给内容搜索：

```bash
find . -type f -name "*.log" -print0 | xargs -0 grep -n "ERROR"
```

涉及删除时先只打印结果确认范围，再执行动作；不要对未验证的项目根目录或变量直接使用 `rm`、`-delete`。

### Windows PowerShell 和 CMD 对应写法

PowerShell 使用 `Select-String` 搜索内容、`Get-ChildItem` 查找文件：

```powershell
# 搜索 Python 文件内容
Get-ChildItem -Recurse -File -Filter *.py |
    Select-String -Pattern "learning_rate"

# 按文件名查找
Get-ChildItem -Recurse -File -Filter *.py
Get-ChildItem -Recurse -File |
    Where-Object { $_.Name -like "*train*" }
```

Windows CMD 可使用 `findstr`：

```bat
findstr /S /N /I "learning_rate" *.py
```

其中 `/S` 递归搜索，`/N` 显示行号，`/I` 忽略大小写。`findstr` 的正则语法与 GNU `grep`/`rg` 不完全相同，复杂代码搜索建议安装 `rg` 或使用 WSL/Git Bash。

### 实际项目中的选择流程

```text
知道文件内容，想找关键词       -> rg / grep
知道文件名模式，想找文件         -> find / rg --files
想快速限定代码文件类型           -> rg -g "*.py" "关键词"
想理解真实定义、引用和类型关系   -> IDE / LSP / Serena
```

例如查找 `batch_size` 的定义和使用：

```bash
rg -n "batch_size" .
rg -n -g "*.py" "batch_size" .
rg -n "batch_size\\s*=" .
rg -n -C 5 "batch_size\\s*=" .
```

`grep` 和 `rg` 是文本搜索工具，不是完整的代码语义分析器；动态导入、别名、继承后的实现和插件注册关系，仍应结合 IDE 的跳转、语言服务器（LSP）或 Serena 判断。

---

## 问题 6：灵龙 2（linglong2）脚底陷入地面

### 现象

在 `output/linglong2_run` 生成的视频、截图或仿真画面中，灵龙 2 的脚底低于地面，看起来像“脚陷进地板里”。这通常不是地面平面的位置错了，而是机器人贴地时参考了错误的高度。

### 先说结论（小白版）

程序为了让机器人站在地面上，会先计算机器人所有 **body 帧** 中最低的 `z` 坐标，然后把机器人整体上下移动：

```python
q[2] -= lowest_height
```

这行代码默认认为“最低的 body 帧”就是“脚底”。但灵龙 2 的脚踝 body 帧原点在脚踝关节处，真正的脚底几何体还在脚踝下方约 7 cm：

```xml
<geom ... pos="0.02 0 -0.069" type="cylinder" />
```

所以，程序把脚踝帧贴到 `z=0` 后，脚底会落到大约 `z=-0.07`，视觉上就会陷入地面。

### 根因

| 项目 | 说明 |
| --- | --- |
| 贴地计算依据 | `forward_kinematics()` 返回的 body 帧原点最低高度 |
| 灵龙 2 的参考帧 | 脚踝处的 body 帧，不是脚底几何体最低点 |
| 脚底相对脚踝 | MJCF 中脚底圆柱的 `pos` 含 `z=-0.069`，约低 6.9 cm |
| 结果 | 脚踝帧在 `z=0` 时，脚底约在 `z=-0.07` |
| 为什么 G1 通常没问题 | G1 有独立的 `toe_link` body，最低 body 帧更接近脚底 |

### 解决思路

给贴地逻辑增加一个“离地补偿值”（`ground_clearance`）：

```
原逻辑：把最低 body 帧放到 z=0
新逻辑：把最低 body 帧放到 z=+ground_clearance
```

灵龙 2 使用 `0.075` 米（7.5 cm）后，脚底大致会回到 `z≈0`，也就是刚好接触地面。这个值是经验起点，不是所有机器人都必须使用的固定常数。

### `0.075` 这个数值是怎么得到的？

它不是随意试出来的数字，首先来自灵龙 2 MJCF 模型中“脚踝 body 帧”和“脚底碰撞几何体”之间的实际几何距离，再用仿真画面做少量微调。

本项目实际使用的灵龙 2 模型是 `assets/LingLong2.0/scene.xml`，其中包含 `LingLong2.0.xml`。在 `LingLong2.0.xml` 里，左右脚踝的 body 内都有类似下面的脚底圆柱几何体：

```xml
<geom
    size="0.007 0.129"
    pos="0.02 0 -0.069"
    quat="0.707105 0 -0.707108 0"
    type="cylinder" />
```

下面按步骤理解每个数字。

| 观察项 | XML 数值 | 小白解释 |
| --- | --- | --- |
| 脚底圆柱的位置 | `pos="0.02 0 -0.069"` | 相对于脚踝 body 帧，圆柱中心向下偏了 `0.069 m`，即 6.9 cm |
| 圆柱半径 | `size="0.007 0.129"` 中的第一个数 `0.007` | MuJoCo 的 cylinder 第一个 `size` 是半径；圆柱横放时，它在竖直方向还会多伸出约 `0.007 m` |
| 脚底最低点估算 | `-0.069 - 0.007 = -0.076 m` | 几何体最低处约比脚踝 body 帧低 7.6 cm |
| 实际采用值 | `0.075 m` | 取接近 7.6 cm 的 7.5 cm，作为稳定、便于调参的初始补偿 |

可以把这件事看成下面这个竖直关系：

```text
脚踝 body 帧原点                 z =  0.000 m
脚底圆柱中心                     z = -0.069 m
脚底圆柱最下沿（近似最低点）      z = -0.076 m
```

原代码把“脚踝 body 帧原点”放到地面 `z=0`，于是脚底最低点自然会进入地面约 7.6 cm。新的补偿逻辑把最低 body 帧抬高约 7.5 cm，正好抵消这个偏差。

#### 为什么是 `0.075`，而不是严格写成 `0.076`？

模型几何计算给出的是约 `0.076 m`，但最终用于仿真的值通常保留一点调节余量。原因包括：

1. 脚在动作中会转动，脚底相对世界坐标系的最低点并不永远等于站立姿势下的理论值。
2. 脚部还有 mesh 几何体；真正视觉上的最低点可能与简化的圆柱碰撞几何体略有差别。
3. 动作重定向、平滑和浮点计算会产生很小的位置差异。
4. 目标是“看起来脚底贴地且不明显穿地”，不是要求每一帧都严格达到数学上的零误差。

因此，`0.075` 应理解为 **根据模型量出来的起始值**。实际验证时，如果脚还略微陷入地面，可以尝试增大到 `0.076` 或 `0.080`；如果脚明显悬空，可以减小到 `0.070`。每次建议只改 `0.002` 到 `0.005 m`（2 到 5 mm），重新生成结果后再判断。

### 三处联动修改

> 这三处要一起改。只改其中一处，可能会出现参数没有传进去、运行时报错，或者新逻辑仍未生效的问题。

#### 第 1 处：在 `general_motion_retargeting/params.py` 增加配置

建议放在已有机器人参数字典附近，新增一张“机器人 → 脚底离地补偿”的表：

```python
GROUND_CLEARANCE_DICT = {
    "linglong2": 0.075,
}
```

含义是：灵龙 2 的最低 body 帧不再贴到 `z=0`，而是保留 7.5 cm 的高度。没有写进这张表的机器人，后续使用默认值 `0.0`，行为与原代码一致。

#### 第 2 处：修改 `scripts/smplx_to_robot_stream.py`

在 `OnlineQposPostprocessor.__init__` 中增加参数，并保存下来：

```python
def __init__(
    self,
    xml_file,
    root_body_name=None,
    smooth_alpha=0.25,
    height_adjust=True,
    root_origin_offset=True,
    ground_clearance=0.0,
    torch_device="auto",
):
    # 其他已有初始化代码保持不变
    self.ground_clearance = float(ground_clearance)
```

找到原来的贴地代码：

```python
q[2] -= lowest_height
```

替换为：

```python
q[2] -= (lowest_height - self.ground_clearance)
```

用大白话理解这行：如果 `ground_clearance=0.075`，整体位置会比原来再抬高 7.5 cm；如果补偿值是 `0.0`，计算结果和原来完全相同。

#### 第 3 处：修改 `handle_wham_gmr.py`

在文件中导入配置：

```python
from general_motion_retargeting.params import GROUND_CLEARANCE_DICT
```

增加一个小工具方法，根据机器人名称取补偿值，未配置的机器人返回 `0.0`：

```python
def _ground_clearance_for_robot(robot_key):
    return float(GROUND_CLEARANCE_DICT.get((robot_key or "").strip().lower(), 0.0))
```

然后在文件中的两处 `OnlineQposPostprocessor(...)` 构造调用里都加上：

```python
ground_clearance=_ground_clearance_for_robot(gmr_args.robot),
```

以及多机器人状态那一处对应使用：

```python
ground_clearance=_ground_clearance_for_robot(state["robot"]),
```

文件中有两处构造位置，分别位于单机器人初始化和多机器人状态初始化；两处都要传参。

### 修改后如何验证

1. 确认配置键写成小写的 `"linglong2"`，并确认数值单位是“米”，不是厘米：`0.075` 代表 7.5 cm。
2. 重新运行生成灵龙 2 仿真结果的流程，不要只打开旧的 `output/linglong2_run` 文件。旧视频不会自动改变。
3. 查看新生成的视频或 viewer 画面：脚底应该接触地面，不能明显穿入，也不应整体悬空。
4. 如果仍然穿地或悬空，以 `0.075` 为中心小幅调整，例如 `0.070`、`0.080`；每次只改几毫米，方便判断变化方向。
5. 检查其他机器人：未加入 `GROUND_CLEARANCE_DICT` 的机器人应保持原来的高度行为。

### 这个办法对不同机器人本体通用吗？

**方法通用，补偿数值不通用。**

| 情况 | 是否可直接使用 `0.075` | 说明 |
| --- | --- | --- |
| 灵龙 2 | 可以作为官方推荐起点 | 其脚踝帧到脚底约有 7 cm 偏差 |
| 有独立 `toe_link`、最低 body 帧已在脚底附近的机器人 | 通常不需要 | 继续使用默认 `0.0`，例如 G1 的设计通常属于这一类 |
| 脚底几何体相对 ankle/body 帧位置不同的机器人 | 不可以直接照抄 | 需要按该机器人的 MJCF/XML 几何位置重新测量 |
| 使用自定义 XML 或修改过脚部 mesh 的机器人 | 不可以假设 | 模型一变，脚底最低点也可能变化 |

判断一台新机器人是否需要补偿，可以按下面的简单方法做：

1. 打开该机器人实际使用的 MJCF/XML 文件。
2. 找到脚踝、脚掌、脚底或 toe 相关的 `<body>` 和 `<geom>`。
3. 比较“贴地使用的最低 body 帧”与“脚底几何体的最低点”之间的垂直距离。
4. 如果脚底比 body 帧低约 `d` 米，就把该机器人配置为约 `d` 的 `ground_clearance`。
5. 重新运行并用画面验证，必要时按毫米级微调。

因此，这个修复不是“所有机器人统一加 7.5 cm”，而是把原来写死的贴地假设改成了**每台机器人可以单独配置**的机制：灵龙 2 配 `0.075`，其他机器人默认 `0.0`，只有确认自身模型存在同类偏差时才增加对应数值。

---

## 问题 7：相机视角变化时，WHAM + GMR 为什么看起来只迁移动作、机器人根部却不动

### 结论先行

当前项目**没有通过 GMR 把机器人根部硬锁死**，也不是 GMR 在运行时“学习”了目标人物的动作。

实际存在两条不同的 WHAM 链路：

| 链路 | 相机运动处理 | 当前状态 |
| --- | --- | --- |
| 标准离线 WHAM | 利用 DPVO 估计相机旋转，由 WHAM 尽量区分“相机在动”和“人在动”，再恢复人体世界坐标运动 | 代码具备该能力 |
| `run.ps1 -> handle_wham_gmr.py` 集成流式链路 | `cam_angvel` 被直接设为零，没有接入 DPVO 动态相机补偿 | 当前项目实际运行方式 |

机器人在结果视频中看起来根部不动，很大程度上可能是因为 **MuJoCo 预览相机默认跟随机器人**，而不是机器人在世界坐标中的根位置真的没有变化。

> 准确表述：WHAM 预测人体的身体动作和根轨迹，GMR 将二者都映射到机器人；预览相机跟随会让根平移在画面中不明显。标准离线 WHAM 可以利用 DPVO 区分相机旋转和人体运动，但当前集成流式链路尚未启用这部分能力。

### 1. 先区分三种“相机/坐标变化”

| 概念 | 当前处理方式 | 是否影响动作数据 |
| --- | --- | --- |
| 输入视频相机运动 | 标准离线 WHAM 可通过 DPVO 估计相机角速度；当前集成链路将其置零 | 会影响 WHAM 对人体世界运动的判断 |
| WHAM Y-up -> MuJoCo Z-up | 使用固定的 X 轴 90 度坐标变换 | 会改变整套姿态和位移的坐标表达，但不是逐帧相机跟踪 |
| MuJoCo 预览相机 | 默认跟随机器人包围盒中心 | 只影响“怎么看”，不修改 CSV、PKL 或 `qpos` |

输入视频相机和 MuJoCo 输出相机是两个完全不同的对象：前者参与人体运动估计，后者只负责渲染展示。

### 2. 标准离线 WHAM 如何区分相机变化和人体动作

完整的离线 WHAM 流程会先通过 DPVO 获得相机轨迹，再从相邻帧的相机旋转计算 `cam_angvel`：

```text
DPVO 相机姿态
  -> camera-to-world / world-to-camera 旋转
  -> 相邻帧旋转差
  -> 相机角速度 cam_angvel
```

对应实现：[dataset_custom.py](lib/data/datasets/dataset_custom.py#L15)。

这里有一个重要限制：当前 `convert_dpvo_to_cam_angvel()` 只使用 DPVO 轨迹的旋转四元数，没有直接使用相机平移。因此它主要帮助处理摇摄、俯仰和旋转镜头；相机前后平移、变焦产生的尺度与深度变化，仍主要依赖 WHAM 的运动先验判断。

WHAM 的 `TrajectoryDecoder` 同时接收以下信息：

| 输入 | 含义 |
| --- | --- |
| `motion_context` | 人体时序运动特征 |
| `last_root` | 上一时刻的人体根姿态 |
| `cam_angvel` | 相机自身的旋转变化 |

然后预测：

| 输出 | 含义 |
| --- | --- |
| `pred_root` | 人体根部在世界坐标系中的方向 |
| `pred_vel` | 人体根部自身坐标系中的速度 |

对应实现：[modules.py](lib/models/layers/modules.py#L160)。

理想情况下，模型会进行如下判断：

```text
画面里人体发生位移
        ↓
结合人体时序特征与相机角速度
        ↓
判断画面运动来自相机还是人体
        ↓
相机转、人体原地不动 -> pred_vel 接近 0
人体真实走动         -> pred_vel 不为 0
```

之后，WHAM 将根部局部速度旋转到世界坐标并逐帧累积：

```python
vel_world = root_rotation @ root_velocity
trans_world = cumsum(vel_world)
```

对应实现：[utils.py](lib/models/layers/utils.py#L6)。标准 WHAM 最终尝试恢复的是：

```text
人体世界根姿态 + 人体世界根位移 + 相对于根部的各关节动作
```

轨迹细化阶段还会根据脚部接触预测修正根速度，以降低站立时的滑脚和根部漂移，见 [utils.py](lib/models/layers/utils.py#L31)。

### 3. 当前集成链路没有启用动态相机补偿

当前 `run.ps1` 启动的是 [handle_wham_gmr.py](handle_wham_gmr.py#L2472) 中的流式实现。该实现直接将相机角速度设为零：

```python
cam_angvel = torch.zeros((1, norm_kp2d.shape[1], 6), device=device)
```

调用 WHAM 时还设置了：

```python
refine_traj=False
```

对应实现：[handle_wham_gmr.py](handle_wham_gmr.py#L1249)。

| 能力 | 当前集成链路状态 |
| --- | --- |
| DPVO 动态相机旋转补偿 | 未启用，`cam_angvel=0` |
| WHAM 足部接触轨迹细化 | 未启用，`refine_traj=False` |
| 人体时序姿态估计 | 已启用 |
| 人体根方向/根速度预测 | 已启用，但输入假设相机没有角运动 |
| 人物裁剪和 2D 关键点归一化 | 已启用 |

因此，当前集成链路**不能保证**面对任意移动镜头时人体世界根部仍然稳定。当镜头变化较大时，WHAM 可能把一部分相机运动误判为人体平移或转身。

即使没有动态相机补偿，局部动作仍可能比较准确，主要因为：

- 人体被持续跟踪，并按每帧人物框归一化；
- 归一化后的关键点更突出肩、肘、髋、膝等关节之间的相对构型；
- WHAM 的预训练时序先验能够过滤一部分观察视角变化；
- 局部骨架动作通常比绝对世界根位移更容易估计。

不过关键点归一化并未完全删除人物位置：`Normalizer` 还会把检测框中心和尺度拼接到输入特征中。因此 WHAM 仍能利用人物在画面中的位置和大小估计根运动。

《Plan.md》中“将相机方向估计与人体朝向估计分开”目前属于 **P2 改进方向**，不是已经在集成流式链路中完整实现的能力，见 [Plan.md](Plan.md#L175)。标准离线 API 具有 DPVO 接口，见 [wham_api.py](wham_api.py#L92)，但当前 `run.ps1` 没有走这条 API。

### 4. WHAM 输出如何进入 GMR

WHAM 输出可以分成局部人体动作和全局根运动两类：

| WHAM 输出 | 含义 |
| --- | --- |
| `poses_body` | 各人体关节相对于父关节的动作 |
| `poses_root_world` | 人体根部在世界坐标系中的方向 |
| `trans_world` | 人体根部世界坐标位移 |
| `poses_root_cam`、`trans_cam` | 相机坐标系下的人体状态 |

当前集成代码优先使用世界坐标结果：

```python
global_orient_global = poses_root_world
transl_global = trans_world
```

只有世界坐标结果不存在时，才退回 `poses_root_cam` 和 `trans_cam`，见 [handle_wham_gmr.py](handle_wham_gmr.py#L789)。

随后执行固定坐标系转换：

```text
WHAM Y-up -> MuJoCo/GMR Z-up
```

```python
root_orient = R_fix * root_orient
trans = trans @ R_fix.T
```

对应实现：[handle_wham_gmr.py](handle_wham_gmr.py#L257)。该变换只负责统一坐标轴，不负责消除逐帧相机运动。

转换后的 `body_pose`、`global_orient`、`transl` 和 `betas` 被送入 SMPL-X，计算每个人体关节的全局位置和全局旋转，再传给 GMR，见 [handle_wham_gmr.py](handle_wham_gmr.py#L1443)。

### 5. GMR 不负责“学习”，而是逐帧求解 IK

GMR 当前运行时没有训练神经网络，它执行的是运动学重定向：

```text
SMPL-X 人体关节目标
        ↓
人体与机器人骨架比例缩放
        ↓
坐标方向和零位偏置
        ↓
为机器人各 body 设置位置/方向目标
        ↓
Mink 逆运动学迭代求解
        ↓
机器人 qpos
```

对应实现：[motion_retarget.py](general_motion_retargeting/motion_retarget.py#L159) 和 [motion_retarget.py](general_motion_retargeting/motion_retarget.py#L182)。

对于灵龙 2，GMR 配置明确建立以下映射：

```text
人体 pelvis -> 机器人 base_link
```

| IK 阶段 | 根部位置权重 | 根部方向权重 |
| --- | ---: | ---: |
| `ik_match_table1` | 100 | 10 |
| `ik_match_table2` | 100 | 5 |

配置位置：[smplx_to_linglong2.json](general_motion_retargeting/ik_configs/smplx_to_linglong2.json#L27)。较高的位置权重说明 GMR 会主动让机器人根部跟随人体骨盆目标，而不是忽略或锁死根部。

灵龙 2 的 `base_link` 也具有自由根关节：

```xml
<body name="base_link" pos="0 0 0.9">
  <freejoint name="base_free" />
</body>
```

见 [LingLong2.0.xml](assets/LingLong2.0/LingLong2.0.xml#L37)。`freejoint` 表示根部具有 3 个平移和 3 个旋转自由度。

最终 `qpos` 的数据结构为：

| 索引 | 内容 |
| --- | --- |
| `qpos[0:3]` | 机器人根部世界位置 |
| `qpos[3:7]` | 机器人根部世界旋转四元数 |
| `qpos[7:]` | 机器人各驱动关节角 |

因此，根部运动没有从数据中被删除。

### 6. 为什么预览中机器人看起来始终不动

当前 `run.ps1` 默认配置为：

```text
CAMERA_FOLLOW=1
ROOT_ORIGIN_OFFSET=0
```

见 [run.ps1](run.ps1#L228) 和 [run.ps1](run.ps1#L258)。

当 `CAMERA_FOLLOW=1` 时，viewer 每一帧都会根据机器人当前包围盒重新设置 MuJoCo 相机的观察中心：

```python
lookat = robot_bounds_center
camera.lookat = lookat
```

对应实现：[robot_motion_viewer.py](general_motion_retargeting/robot_motion_viewer.py#L251)。最终视觉效果可能是：

```text
机器人在世界坐标中移动
        +
预览相机同步跟随机器人
        =
机器人在输出视频中始终接近画面中央
```

所以，“画面中根部看起来不动”不能证明 `qpos[:3]` 没有变化。

### 7. `ROOT_ORIGIN_OFFSET` 也不是根部锁定

启用 `root_origin_offset` 时，在线后处理器只会记录首帧根部水平位置并从后续帧中减去：

```python
if self.xy_origin is None:
    self.xy_origin = q[:2].copy()
q[:2] -= self.xy_origin
```

这只是把首帧位置平移到坐标原点，后续相对位移仍然保留：

```text
处理前首帧 XY = (12.3, -4.5)
处理后首帧 XY = (0.0, 0.0)
后续帧 XY     = 相对首帧的真实位移
```

当前 `run.ps1` 默认 `ROOT_ORIGIN_OFFSET=0`，所以集成链路默认连首帧原点平移也不做。离线 `scripts/smplx_to_robot.py` 默认启用它，但同样不会逐帧锁定根部。

后处理中的指数平滑和贴地高度调整也只会让根运动更连续、修正 `q[2]` 高度，不会把每帧的 `q[:3]` 强制设为固定值。

### 8. 如何验证机器人根部是否真的移动

不要只看输出视频，应同时检查数值结果：

| 检查方法 | 判断依据 |
| --- | --- |
| 查看 CSV | 比较多帧的前 3 列；数值变化说明根位置在移动 |
| 查看 PKL | 检查 `root_pos` 的逐帧变化、累计路径长度和速度 |
| 关闭预览跟随 | 设置 `CAMERA_FOLLOW=0` 后重新生成视频，观察机器人相对地面的移动 |
| 区分位置与方向 | `qpos[0:3]` 不变只表示位置固定，还需检查 `qpos[3:7]` 是否发生根旋转 |
| 对照 WHAM 中间结果 | 分别检查 `trans_cam`、`trans_world`、`poses_root_cam` 和 `poses_root_world` |

推荐统计以下指标：

```text
root_xy_range = max(root_xy) - min(root_xy)
root_z_range  = max(root_z) - min(root_z)
root_path_len = sum(norm(root_pos[t] - root_pos[t - 1]))
```

如果 `root_path_len` 明显大于零，但输出画面中的机器人始终居中，基本可以判断是预览相机跟随造成的视觉效果。

### 9. 如果需求是真正“固定根部，只迁移局部动作”

当前项目没有提供严格的根部锁定。若比赛或部署确实需要机器人原地模仿，应明确选择锁定范围：

| 策略 | 处理方式 | 适用场景 |
| --- | --- | --- |
| 只锁水平位置 | 固定 `q[0:2]`，保留高度和根旋转 | 原地屈膝、转身、上肢动作 |
| 锁水平位置和根朝向 | 固定 `q[0:2]` 与根 yaw，保留贴地高度 | 始终面向固定方向的动作模仿 |
| 完全锁根 | 固定 `q[0:3]` 和 `q[3:7]`，只输出 `q[7:]` | 固定基座或只评分驱动关节的任务 |
| 保留完整根运动 | 不锁根，使用 WHAM/GMR 根轨迹 | 行走、转身和位移动作 |

根部锁定应作为明确、可配置的后处理或 IK 约束实现，不能依赖预览相机跟随产生的视觉效果。实现前还需要确认比赛评分是否包含浮动根：如果只评估驱动关节角，锁根可能合理；如果需要复现人物的行走轨迹，锁根会丢失关键动作信息。

### 10. 当前能力边界与后续改进

| 项目 | 当前事实 | 建议 |
| --- | --- | --- |
| 输入相机旋转解耦 | 标准离线 WHAM 有 DPVO 接口，集成流式链路未接入 | 将真实 `cam_angvel` 接入 `wham_thread()` |
| 输入相机平移解耦 | `convert_dpvo_to_cam_angvel()` 不使用 DPVO 平移 | 单独评估相机平移、变焦和根深度漂移 |
| 足部接触轨迹细化 | 集成链路设置 `refine_traj=False` | 评估性能开销后启用，或实现在线等价方案 |
| 根部锁定 | 当前没有硬锁定 | 根据评分协议增加显式、可配置的根部约束 |
| 预览判断 | 默认相机跟随会掩盖世界位移 | 调试时关闭相机跟随，同时检查数值输出 |
| `Plan.md` 描述 | “相机方向与人体朝向分开”属于规划目标 | 在实验记录中明确标注“已实现/未实现” |

### 一句话记忆

```text
WHAM 负责估计人体动作和根轨迹；
GMR 负责用 IK 把人体目标转换成机器人 qpos；
MuJoCo 相机只负责“怎么看”；
当前集成流式链路没有启用 DPVO 相机角速度，机器人看起来原地不等于根部真的被锁住。
```
