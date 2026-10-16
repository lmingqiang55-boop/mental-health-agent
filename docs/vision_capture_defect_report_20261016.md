# 摄像头采不到表情：三条前端断点（2026-10-16）

- 日期：2026-10-16
- 触发：队友反馈"已经打开摄像头聊了几轮，回复里完全没有表情细节"
- 发现方式：核对后端实际收到的数据 + 用**假摄像头**（Chromium `--use-fake-device-for-media-stream`）
  在真实前端 + 真实后端上复现，并用**同一窗口重发 segment** 的方式区分"竞态"与"窗口错位"
- 结论摘要：**采集与推理链路本身是好的**（帧上传 200、segment 200、宽窗口下 `frame_count=8`）。
  "没有表情"是**三条互不相同的前端断点**造成的，都在前端，后端判定一行未改：

| 编号 | 断点 | 触发条件 | 证据强度 |
| --- | --- | --- | --- |
| **A** | **只打字不点麦克风，采集永不启动** | 在手动输入框里打字 | 已复现（决定性） |
| **B** | **续测会话（`turn_count>0`）采集永不启动** | 刷新 / 回来接着聊 | 已复现（决定性） |
| **C** | **打字路径的 1 秒窗口抓不到刚落地的帧** | 采集已启动并打字 | 已复现（同窗口重发对照） |
| D | 直接打开 `/assess/session/:id` 会绕过摄像头开关 | 只发会话链接 | 已复现 |

**A、B、C 的共同根源**：采集启动只挂在 `begin()` 一个入口上，而 `begin()` 只由"点击麦克风按钮"触发。

---

## 一、先明确：链路与模型都是好的

| 环节 | 实测结果 |
| --- | --- |
| 假摄像头 + 完整流程（同意 → 设备检查拨开摄像头 → 开始测评 → 点麦克风） | 界面显示 **`摄像头已开启 · 已上传 7~13 帧`** |
| `GET /api/vision/status` | `{"provider":"emotiefflib","state":"ready","real_analysis":true}` |
| YuNet 人脸检测权重 | **已落盘**：`backend/vision/weights/face_detection_yunet_2023mar.onnx`（227.1 KB） |
| 后端日志 | 无 `YuNet 人脸检测不可用…降级为 Haar` |
| `POST /api/vision/frame` | 200；宽窗口 segment 能读回全部帧（`frame_count=8`） |
| `POST /api/vision/segment` | 200（**从不报错**，只是窗口内常常没有已落地的帧） |

所以**不是**模型不可用、不是权重缺失、不是 segment 端点坏了、也不是阈值把表情全挡掉了。

---

## 二、断点 A（主要）：只打字，采集永不启动

### 机制

```ts
// [AssessSession.vue:344-356] 手动输入通道
async function sendManualText() {
  const text = manualText.value.trim()
  ...
  visionSnapshot = await segment(utteranceId, Math.max(0, now - 1000), now)   // ← 先问视觉
```

```ts
// [useVision.ts:104-107] segment() 的第一行
async function segment(utteranceId, startMs, endMs) {
  if (!active.value || !sessionId || !captureId) return null    // ← active 只在 start() 里置真
```

而 `start()`（即 `startVision`）**只被 `begin()` 调用**，`begin()` **只被麦克风按钮触发**：

```
[AssessSession.vue:528]  @click="!started ? begin() : recording ? finishRecord() : startRecord()"
```

打字路径**完全不经过** `begin()`。后果有两层：

1. 采集从未启动 → `segment()` 立刻 `return null` → 每轮都没有视觉快照；
2. `started` 一直为 `false`，而采集状态行在 `v-if="started && !closing"` 里
   → **连"摄像头没开"这行提示都看不到**，界面上没有任何异常迹象。

### 复现证据（决定性）

全新会话（`turn_count=0`）+ 预置 `sessionStorage['xq_device_cam']='1'`，**只打字、绝不点麦克风**：

| 观察点 | 实测 |
| --- | --- |
| 打字前 / 打字后有没有采集状态行 | `False` / `False` |
| `active_vision_capture_id` | **`None`**（从未发出 `POST /api/vision/capture`） |
| `frame` 响应条数 | **0** |
| 消息里带视觉快照的条数 | **0** |

脚本：`scripts/vision_typed_repro.py`

### 已验证的绕过办法

**先点一次麦克风按钮**（在 `!started` 时它只执行 `begin()`，**不会真的开始录音**），采集随即启动，
之后打字就能带上视觉快照。对照实测：

| 做法 | 采集状态行 | `capture_id` | frame 200 条数 |
| --- | --- | --- | --- |
| 只打字 | **（不存在）** | `None` | 0 |
| 先点一次麦克风，再打字 | **`摄像头已开启 · 已上传 13 帧`** | `cap-…` | 13 |

### 建议修法（**尚未实施**）

把启动采集抽成共用函数，`begin()` 与 `init()`（续测）都调它；并让打字路径在
`started` 为假时先补启动一次——即"第一条消息无论是说出来的还是打出来的，都先确保采集在跑"：

```ts
/** 启动采集：begin()（新会话首次开始）与 init()（续测）共用同一套兜底。 */
async function startVisionSafely() {
  if (!assess.camEnabled || closing.value) return
  try {
    await startVision(sid, originMs())
    camFailed.value = false
  } catch {
    camFailed.value = true
    toastWarn('摄像头不可用，已切换为仅语音')
  }
}
```

- `begin()` 里原来的 `try/catch` 换成 `await startVisionSafely()`
- `init()` 末尾补 `if (started.value) await startVisionSafely()`
- `sendManualText()` 在 `segment()` 之前补 `if (!started.value) await startVisionSafely()`

改动约 15 行，**只动前端**，不涉及后端阈值与判定。

---

## 三、断点 B：续测会话不启动采集

`init()` 在恢复历史后直接宣布"已经开始了"：

```ts
// [AssessSession.vue:179-180]
// 已聊过（续测）：无需再点「开始对话」
started.value = state.turn_count > 0
```

`init()` 里**没有任何地方补启动采集**，于是续测时 `begin()` 再也不会被调用。
界面那行会一直停在 `摄像头开启中…`（`visionStatus` 的兜底分支），
**看起来摄像头在工作，实际一帧都没传**——因为"函数根本没被调用"不会抛异常，
`camFailed` 永远是 `false`。

复现（`turn_count=2`、`xq_device_cam=1`、直接打开会话页）：

| 观察点 | 实测 |
| --- | --- |
| 进入时 / 再等 8 秒 | `摄像头开启中…` / 仍然 `摄像头开启中…` |
| `active_vision_capture_id` | **`None`** |

脚本：`scripts/vision_resume_repro.py`

---

## 四、断点 C：打字路径的 1 秒窗口抓不到刚落地的帧

采集已经跑起来、帧也在上传，打字时仍然可能拿不到快照。原因是窗口与帧的落地时序不匹配。

```ts
// [AssessSession.vue:352-353] 打字路径的窗口：固定 1 秒，右端点就是"现在"
const now = originMs()
visionSnapshot = await segment(utteranceId, Math.max(0, now - 1000), now)
```

而后端按**半开区间**筛选已入库的帧：

```python
# [backend/api/vision.py:188-190]
frames = [item.state for item in session.vision_frames
          if item.capture_id == request.capture_id
          and request.start_ms <= item.captured_at_ms < request.end_ms]
```

帧是 `setInterval(sendFrame, 1000)` 每秒一帧，而每帧要经过
`canvas.toDataURL` 编码 → base64 → 上传 → 服务端解码 + 推理 → 入库，
落库时刻比"发出时刻"晚几百毫秒。于是打字那一刻，**最新一帧往往还在路上**，
1 秒窗口里已落地的帧数常常是 0 → `aggregate_frames([])` 返回 `None` → 快照为 `null`。

### 复现证据（同窗口重发对照，决定性）

浏览器那次打字发出的 segment 窗口是 `[13662, 14662)`，返回 `frame_count=0 / snapshot=null`；
**事后用完全相同的窗口重发一次**（只换 `utterance_id`）：

```
重发窗口 [13662, 14662)  宽度=1000ms  frame_count=1  （该窗口内共发出过 1 帧：[14109.9]）
```

同一窗口，先 0 后 1 —— 证明那一帧当时**还没入库**，而不是窗口位置错了。
（另有更直接的对照：窗口右端点若正好等于最后一帧的时间戳，因半开区间必然是 `frame_count=0`。）

`scripts/vision_typed_repro.py` 的第②组（先点麦克风、等 12 秒、再打字）实测
**11 帧全部上传成功，但"带快照的消息"仍是 0**；连同前面几次复现，
打字路径在 **4 次独立复现中每次都是 0 条带快照的消息**——所以这不是偶发竞态，
而是打字通道**基本必然**拿不到视觉快照。

**这一条只影响"打字"通道**：语音通道的窗口是整段发言（数秒到数十秒），帧足够多，不受影响。

### 建议修法（**尚未实施**）

把打字路径的窗口放宽并把右端点往前留出余量，例如
`segment(utteranceId, Math.max(0, now - 4000), Math.max(0, now - 300))`，
或在打字时**主动补采一帧**再截图。具体取多大需要真机试一次。

---

## 五、断点 D（用法陷阱）：直达会话链接开不了摄像头

摄像头开关**只存在于设备检查页** `/assess/check`，状态存在 **sessionStorage**
（`writeSessionFlag`，键 `xq_device_cam`；sessionStorage **按标签页隔离**）。

```
/assess/consent  →  /assess/check（在这里拨开摄像头）  →  /assess/session/:id
```

直接打开 `/assess/session/:id`（或把它发给别人）时 sessionStorage 里没有这个键 →
`camEnabled = false` → 采集整段跳过。**本次排查自己踩过这个坑**：最初给出的正是直达会话链接。

| 路径 | sessionStorage | 采集状态文案 | 后端 |
| --- | --- | --- | --- |
| A. 直接打开会话链接 | `null` | `仅语音模式（摄像头未开启）` | `capture_id = None` |
| B. 完整流程 | `1` | **`摄像头已开启 · 已上传 7 帧`** | `state = ready` |

脚本：`scripts/vision_capture_repro.py`

---

## 六、自检：看一眼那行采集状态

聊天区上方有一行采集状态（`.session__vision`）。**注意它只在 `started` 为真时存在**——
所以"页面上没有这一行"本身就是断点 A 的信号。

| 界面文案 | 含义 |
| --- | --- |
| （**页面上没有这一行**） | 断点 A：你在打字，`begin()` 没被触发，采集从未启动 |
| `仅语音模式（摄像头未开启）` | 断点 D：摄像头开关没开（多半绕过了设备检查页） |
| `摄像头开启中…` | 断点 B：开关开了但采集从未启动（续测）；或起流卡住 |
| `摄像头已开启 · 已上传 N 帧` | 帧在传；此时若仍无表情细节，看断点 C（打字）或闸门（无人脸/效价不足） |
| `摄像头已开启，但数据未能上传：…` | 上传失败，`…` 就是原因 |

**注意一个误导**：`uploadError` 被 frame 与 segment 共用，而 `sendFrame` 每成功一帧就把它清空
（`useVision.ts:90`），所以 segment 的失败会在 1 秒内被擦掉、状态行照样显示绿色。

---

## 七、更正：本报告前两版的两处错误结论（已推翻）

排查过程中出现过两个错误结论，在此明确撤回，避免以后被引用：

| 曾说过的 | 实际情况 |
| --- | --- |
| "`vision_segments = 0` → segment 通路断了" | **错**。`SessionState.vision_segments`、`vision_frames`、`last_visual_observation_turn`、`dialogue_frames` 在 `backend/models/states.py` 里都是 `Field(..., exclude=True)`，**API 永远不会返回**。把这些字段读成 0/None 是无意义的；`segment` 实际返回 200 并正常入库。 |
| "时间基准错位：`start(sid, originMs())` 传了流逝毫秒数当原点" | **错**。实测帧时间戳（3153…16103ms）与 segment 窗口（`[13662,14662)`）在同一时间轴上，能互相覆盖，不存在量纲错位。真实原因是断点 C 的落库时序。 |

**可用的读数**：`active_vision_capture_id`（未排除）与 `Message.vision_snapshot`（未排除）——
这两个才是判断"有没有在采、有没有带上"的可靠字段。

---

## 八、原 2026-10-12 报告已删除，其结论以本表为准

`docs/vision_multimodal_defect_report_20261012.md` 已于 2026-10-16 **删除**
（它从未入 git；删除前留了一份副本在 `data/diagnostics/…archived.md`）。
删除原因：它列的问题绝大部分**已经修好**，继续留在 `docs/` 会误导后来的人。
下表是逐条核对当前代码后的**权威结论**，以后以这张表为准。

| 编号 | 10-12 记录 | 现状 |
| --- | --- | --- |
| P0-1 | 一致性计算是硬编码空壳 | **已修**：`report_builder.py:124-125` 已由 `consistency.score/level` 取值 |
| P0-2 | 表情采纳路径不可达 | **已修**：`min_confidence` 0.8→**0.6**，新增 `select_visual_checkin`、`select_visual_tone` 两条通道，阈值集中到 `backend/core/vision_thresholds.py` |
| P0-3 | Haar 漏检约 43% | **已修**：改用 **YuNet**（`backend/vision/face_weights.py`，SHA256 校验 + Haar 降级） |
| P1-1 | 关摄像头必然 422 | **已修**：`ensureCaptureId()` 关闭时复用同一 id |
| P1-2 | 前端静默吞掉视觉错误 | **部分修**：已上报 `uploadError`，但被每秒一次的成功帧擦掉（见第六节） |
| P1-6 | 无采集状态指示 | **已修**：`visionStatus` 多态文案；但断点 A 下整行不渲染 |

上一轮沟通中曾按这份旧文档向队友转述"P1-1 / P1-2 / P1-6 仍未修"，**该转述有误**，以本表为准。

---

## 九、环境事实

- **会话是进程内存储，重启即清空**（`backend/core/session_manager.py:8`），且有 **2 小时 TTL**
  （`SESSION_TTL = timedelta(hours=2)`）。视觉逐帧数据从未落盘，想留证据必须及时导出。
- `camEnabled` 在 **sessionStorage**（按标签页），不是 localStorage。
- 视觉模型**懒加载**：`not_loaded` 是正常初始态，第一帧到达时才载入；`state` 是**进程级**的，
  不能用来判断某个会话有没有在传帧。
- 单帧服务端处理耗时：**中位 53 ms**（用纯色图测的，YuNet 会提前退出，真实人脸会更慢）。
- `getUserMedia` 要求安全上下文：必须 `127.0.0.1` 或 `localhost`。
- `POST /api/vision/segment` 的 `end_ms` 有字段上限，超过会 422。

---

## 十、复现脚本

| 脚本 | 用途 |
| --- | --- |
| `scripts/vision_typed_repro.py` | 断点 A：只打字 → 采集从未启动（含"先点麦克风"对照） |
| `scripts/vision_resume_repro.py` | 断点 B：续测会话永不启动采集 |
| `scripts/vision_capture_repro.py` | 断点 D：直达链接 vs 完整流程 |
| `scripts/dump_session_snapshot.py` | 导出会话完整状态为 JSON（在重启/TTL 前留证据） |

```powershell
# 在仓库根目录下执行；用你本机装了依赖的解释器（见 docs/environment.md）
$env:NO_PROXY = "127.0.0.1,localhost"
python -X utf8 scripts\vision_typed_repro.py
python -X utf8 scripts\dump_session_snapshot.py <session_id>
```

脚本默认连 `http://127.0.0.1:4180`（前端）与 `http://127.0.0.1:8011`（后端），
端口不同时把地址作为第一个参数传进去即可。

---

## 十一、待办

1. **断点 A / B 未修** —— 建议修法见第二、三节，合计约 15 行，只动 `AssessSession.vue`。
2. **断点 C 未修** —— 需要定一个合适的窗口宽度，建议真机试。
3. **用真实人脸验证一次采纳通道**：假摄像头的合成画面没有脸（实测 `face_detected=False`、
   `valid_frame_count=0`），所以假设备**只能验证采帧与入库，验证不了"表情被说出口"**。
   验证口径：同一句偏负面的文本 + 连续 3 帧以上偏负效价 →
   提示词出现 `【本轮视觉观察】`，回复出现"看起来 / 没什么精神"等说法
   （见 `VISUAL_MENTION_PHRASES`）。
4. 断点 D 是用法问题；若要降低踩坑概率，可在仅语音模式下给一次轻提示。
