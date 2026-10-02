# 语音识别接入与交接

第一版实现后端完整录音转写，不实现前端页面。用户按住/松开对应一条消息；
录音有多句话或停顿仍只提交一个聊天回合。主链为：完整文件上传 → PyAV
解码/16 kHz 单声道重采样 → FunASR + SenseVoiceSmall → 清理特殊标签 →
前端与本句视觉汇合 → 自动提交 `/api/chat`。ASR 不调用 LLM、不改写原文。

本轮已完成 SenseVoice 与 faster-whisper Small 的本机对照，保留 SenseVoice
作为生产路径；对照模型只用于基准脚本。耗时、识别样本和待验收项见
[2026-10-02 验证记录](speech_validation_2026-10-02.md)。单字“嗯”的合成样本
在两种模型上均未通过；随后用户提供的一份真人录音在两种模型上均识别正确，
SenseVoice 的默认自动语言模式也通过。其他发音、设备和噪声条件仍待验收。
随后用户录制的 5 条单句均通过 SenseVoice 和正式上传路由；五合一完整录音
可识别；用户据此将录音上限确定为 60 秒，五合一原文件及衍生的 60 秒样本
均通过正式上传接口，具体结果见验证记录。

## 安装与启动

在项目目录使用 Miniforge 环境：

```powershell
conda activate mental-health-agent
python -m pip install -r requirements.txt
# NVIDIA GPU：先从官方源安装对应的一对 CUDA 包。
python -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements-audio.txt
```

CPU 安装把第二条 pip 命令的 index-url 改为 `https://download.pytorch.org/whl/cpu`。
不要混用不同版本的 torch、torchaudio；已有可用包时先核对环境，不要求更换其他
模块的依赖。PyAV 的 Windows wheel 自带 FFmpeg 库，无需设置外部 ffmpeg 路径。

在本地 `.env` 配置 `ASR_PROVIDER=sensevoice`、`ASR_DEVICE=cuda:0`（或 `cpu`），
再启动服务。应用启动和 SenseVoice 基准脚本会从项目根目录读取 `.env`；
显式设置的进程环境变量优先于文件值，不依赖启动命令所在目录。
Web 依赖至少需要 FastAPI 0.115.7 与 Starlette 0.44.0，上传解析器需要后者的
`max_part_size` 参数；安装 `requirements.txt` 会应用这些约束。

启动命令：

```powershell
python -m uvicorn backend.main:app
```

默认 `ASR_PROVIDER=disabled`，文字/评估功能可独立运行；不会以 Mock 假装转写。
启用时在应用启动阶段加载并用一秒空波形预热，加载失败时状态为 `unavailable`，
转写返回 `503 ASR_UNAVAILABLE`。`GET /api/audio/status` 的 `state=ready` 才表示
模型可接收请求；`/api/health` 仅表示 Web 服务可用。启用 ASR 建议单个 worker，
每个额外 worker 都会各加载一份模型；`--reload` 也会重新加载。

首次启动会从 ModelScope 下载 `iic/SenseVoiceSmall` 权重与 tokenizer。
使用 FunASR 包内置模型实现，`trust_remote_code=False`，不执行模型仓库下载的
Python 文件。默认 revision 为 `master`，可通过 `ASR_MODEL_REVISION` 指定已验证
的发布版本；已下载的本地模型目录也可用 `ASR_MODEL` 配置。模型缓存由
ModelScope 管理，可用 `MODELSCOPE_CACHE` 指定；离线运行应事先准备完整模型。
上传原始音频不写入模型缓存，不长期保存；模型缓存属于运行依赖。

Windows 中文缓存路径使用 Python 读取 tokenizer 模型字节，再交给 SentencePiece，
避免其本地文件打开器的 Unicode 路径兼容问题；无需移动缓存或改安装目录。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `ASR_PROVIDER` | `disabled` | `disabled` 或 `sensevoice` |
| `ASR_MODEL` | `iic/SenseVoiceSmall` | 模型标识或完整本地模型目录 |
| `ASR_MODEL_REVISION` | `master` | ModelScope revision |
| `ASR_DEVICE` | `cpu` | `cpu` 或 `cuda:0` 等设备 |
| `ASR_LANGUAGE` | `auto` | auto/zh/en/yue/ja/ko |
| `ASR_MAX_UPLOAD_MB` | 10 | 文件大小，最大可配置为 20 MiB |
| `ASR_MAX_DURATION_SECONDS` | 60 | 录音区间和实际解码时长，最大可配置为 60 秒 |
| `ASR_TIMEOUT_SECONDS` | 60 | 解码、排队、推理总等待上限 |
| `ASR_MAX_PENDING` | 4 | 上传、会话检查、排队和推理合计的请求数上限 |
| `ASR_CPU_THREADS` | 4 | FunASR CPU 线程数 |

模型实例只由单个工作线程调用，避免并发修改 FunASR 的内部状态；解码和 ASR
均在会话锁外执行。路由在读取录音前预留容量，上传和转写前后的会话检查
也计入上限；容量已满立即返回 `ASR_BUSY`，不读取请求体。模型未就绪也在
读取录音前返回 `ASR_UNAVAILABLE`，此时不继续校验表单或会话。
上传失败、会话失效或提交推理前取消会释放槽位。请求超时不代表正在执行的
本地推理已停止，仍占用处理槽位直到完成；超时或取消的排队任务在工作线程
取到时跳过。已提交工作和路由都结束后才释放槽位，避免录音在队列外积压。
转写前后的同步会话有效性查询在线程池执行，等待其他聊天持有的会话锁时，
不会阻塞事件循环；查询仍可能等待锁释放。

## 上传协议与限制

`POST /api/audio/transcribe` 为 multipart，六项必填：

| 字段 | 含义 |
| --- | --- |
| `file` | 停止录音并完成最后一次 dataavailable 后的完整文件 |
| `session_id` | 已创建且未过期的会话 |
| `utterance_id` | 本次录音唯一标识；同一发言重试复用 |
| `capture_id` | 音频与图像共用的连续采集时间轴标识 |
| `recording_start_ms` | 实际录音开始，相对时间轴起点的非负毫秒数 |
| `recording_end_ms` | 实际录音结束，同一时间轴，必须大于开始 |

上传字段不能重复，文件名只作展示，不用于拼接本地路径。支持 MIME：
`audio/webm`（Opus）、`audio/ogg`（Opus/Vorbis）、`audio/wav`、`audio/wave`、
`audio/x-wav`、`audio/mp4`/`audio/x-m4a`（AAC/Opus）、`audio/mpeg`（MP3）、
`audio/flac`，Ogg 也接受 `application/ogg`。MIME 可携带 codecs 参数，实际容器
必须与 MIME 匹配；不能把 WAV 改名为 WebM。文件要求仅一条音轨且无视频，
采样率 8～192 kHz，1～8 声道。支持容器不等于验收了所有浏览器和编码器组合。

multipart 流在解析前累计限制总字节数（文件限额 + 64 KiB 表单开销），字段
单项最多 1 KiB；接受的文件保持内存处理。解码逐帧检查真实时长，不信任文件名
或客户端时长；重采样调用真实 resampler，并在末尾 flush，不能只修改采样率标签。
允许少量编码器尾部 padding，但不静默裁断超限录音。

客户端采集区间与实际解码时长相差超过 `max(250 ms, 区间时长 × 2%)` 时返回 `AUDIO_TIME_MISMATCH`，
以发现收尾不完整或时间轴错误。实际录音区间可包含静音，不能当成 VAD 边界。
没有最短录音门槛，短回答可进入识别；完全静音或清理后无文字返回 `NO_SPEECH`。
模型返回文本超过 4000 字时明确报错，不截断、不拆成多个聊天回合。

## 前端调用示例

以下是交接示例，不是已实现的录音页面。预先完成麦克风权限与设备准备，
在实际开始/停止采集时记录时间；不要把等待权限弹窗的时间算入录音。

```javascript
const form = new FormData();
form.append('file', completeBlob, 'recording.webm'); // Blob.type 保留 recorder.mimeType
form.append('session_id', sessionId);
form.append('utterance_id', utteranceId);
form.append('capture_id', captureId);
form.append('recording_start_ms', String(recordingStartMs));
form.append('recording_end_ms', String(recordingEndMs));
const response = await fetch('/api/audio/transcribe', { method: 'POST', body: form });
const result = await response.json();
if (!response.ok) throw result.error;
// 先核对会话与录音仍有效，再与本句视觉任务汇合。
const chatBody = { ...result };
if (alignedVision != null) chatBody.vision_snapshot = alignedVision;
const chatResponse = await fetch('/api/chat', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(chatBody),
});
```

取消、离页、切换会话和重新开始要使旧结果失效。松开后等待最后一个
`dataavailable` 和 `stop` 再上传；最长时长、失焦与移出后松开行为由前端实现。
转写失败可保留录音重试；聊天失败复用已得到的文字、时间和视觉快照。
自动发送成功文本，不增加确认/编辑步骤；处理中禁用新一轮及最终评估。

## 聊天、视觉与评估对接

聊天的 `speech` 和 `utterance_id` 为新增可选字段，旧文字请求继续可用。
提供 `speech` 必须同时提供 `utterance_id`。只有聊天成功才写一条 user + 一条
assistant 并增加 `turn_count`；ASR 不保存消息、不更新随机副语言特征。
会话查询中的用户消息可查到 `utterance_id`、`speech` 和原 UTC `created_at`。

同一 `(session_id, utterance_id)` 的相同文本（首尾 trim 后）、录音时间和视觉
内容重试，返回首次成功响应，包含首次回合数，即使会话已有后续回合也不变。
任一内容变化返回 `UTTERANCE_CONFLICT`；未提供 ID 的文字请求保持原来逐次提交
语义。快照自动生成的 `timestamp` 不参与去重；快照内容参与，因此不能重取表情
后重试。策略失败不保存消息或成功缓存，允许原 ID 重试。

语音路径只使用请求中的本句快照；没有快照时不借用最近一帧，副语言特征保持
缺测。视觉队员负责同一 `capture_id` 上 `[start, end)` 区间的帧筛选、聚合和
会话汇总；本轮没有实现视觉帧时间字段、区间聚合或前端采样调整。
无帧、无脸和数值缺测不应填 0；聊天重试与晚到帧不能修改原快照。

最终评估可以仅发送 `session_id`，也可以提供完整 `evaluation_input`。
已有发言标识时，完整输入必须保留原消息顺序、角色和文本，后端按原记录保留
语音元数据、`created_at`、音频快照；若改写/删减/重排返回 `HISTORY_CONFLICT`，
避免把重复文本错配到不同录音。时间元数据不要求加到严格评估顶层，评估 Prompt
仍只读取原文与既有视觉结构。内存记录和成功重试缓存沿用会话 TTL，重启清空。

## 错误与重试

统一响应为 `{ "error": { "code": "...", "message": "..." } }`。

| HTTP | code | 处理 |
| --- | --- | --- |
| 404 | `SESSION_NOT_FOUND` | 新建会话；旧结果失效，不能提交到新会话 |
| 422 | `VALIDATION_ERROR` | 修正字段、时间顺序或 multipart |
| 415 | `UNSUPPORTED_AUDIO_FORMAT` | 用已支持的真实容器/MIME 重新录音 |
| 422 | `INVALID_AUDIO` | 检查文件完整性或重新录音 |
| 413 | `AUDIO_TOO_LARGE` | 缩短录音或降低编码码率 |
| 422 | `AUDIO_TOO_LONG` | 分次录音，不会自动切聊天回合 |
| 422 | `AUDIO_TIME_MISMATCH` | 检查实际采集时间和音频收尾 |
| 422 | `NO_SPEECH` | 提示未识别到语音，不发占位文本 |
| 422 | `TRANSCRIPT_TOO_LONG` | 缩短录音，不静默截断 |
| 503 | `ASR_UNAVAILABLE` | 检查依赖、配置、模型加载/推理 |
| 503 | `ASR_BUSY` | 稍后重试原录音 |
| 504 | `ASR_TIMEOUT` | 保留原录音，稍后重试 |
| 409 | `UTTERANCE_CONFLICT` | 复用原聊天请求；新发言用新 ID |
| 409 | `HISTORY_CONFLICT` | 用查询得到的原完整消息触发评估 |
| 503 | `POLICY_UNAVAILABLE` | 仅重试聊天，不重新 ASR 或取表情 |

## 验证方法与来源

```powershell
python -m pytest -q tests
python -m scripts.benchmark_asr --device cuda:0 --language zh --repeat 3 samples/3s.wav samples/10s.wav samples/30s.wav
```

基准脚本读取用户提供的测试音频，报告模型加载/预热、解码和推理耗时。
模型首次下载、网络上传、视觉准备和策略回复要分别测量；脚本没有这些环节，
不把推理时间冒充松开到最终回复时间。建议使用虚构语音，并检查“嗯”“没有”、
睡眠表述、否定词、多句话和尾字；合成音频不能替代真人麦克风验收。

可选 faster-whisper 对照使用相同解码器、完整波形和固定中文，不启用 VAD。
生产服务无需安装对照依赖；模型由 `--model-cache` 指定缓存位置：

```powershell
python -m pip install -r requirements-audio-compare.txt
python -m scripts.benchmark_whisper --model small --model-cache models/whisper --revision 536b0662742c02347bc0e980a01041f333bce120 --device cuda --language zh --repeat 3 samples/3s.wav samples/10s.wav samples/30s.wav
```

CPU 对照用 `--device cpu`（int8），GPU 用 float16；beam size 为 5。
脚本完整消费 Whisper 的惰性 segments 生成器后才停止计时，多段结果合并为一条
文本。Windows 下从当前 PyTorch 包动态查找 CUDA DLL，并通过官方 `files=`
接口加载中文缓存路径中的模型字节，不依赖固定安装路径。

实现参考：[FunASR SDK](https://github.com/modelscope/FunASR/blob/main/docs/tutorial/README.md)
的 AutoModel、波形输入与模型复用；[SenseVoice](https://github.com/QwenAudio/SenseVoice)
的整段推理与特殊标签；[faster-whisper audio.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/audio.py)
的 PyAV downmix/resample 和末尾 flush。标签清理与上传边界是本项目适配，未复制
上游富文本表情输出；对照脚本参考 [faster-whisper 用法](https://github.com/SYSTRAN/faster-whisper#usage)
的 WhisperModel、精度参数和生成器迭代。未来可对照 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
和 [Silero VAD](https://github.com/snakers4/silero-vad)；本轮不安装它们、不宣称流式。

软件与模型许可分别检查：[FunASR 软件 MIT](https://github.com/modelscope/FunASR/blob/main/LICENSE)、
[SenseVoice 软件 MIT](https://github.com/QwenAudio/SenseVoice/blob/main/LICENSE)、
[SenseVoiceSmall 模型卡](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)与
[FunASR 模型协议](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)。
模型权重按独立模型协议使用，保留来源、作者和模型名称等约定；发布前核对所用
模型卡指向的具体版本。权重属于运行依赖，不提交进本项目代码仓库。
