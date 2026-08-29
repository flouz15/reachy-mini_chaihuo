# 柴火基地车 Reachy Mini 智能助手（皮皮虾）

面向 Reachy Mini 的中文多模态交互项目，集成阿里云百炼 ASR、LLM、TTS、VLM，支持
语音唤醒、Web Dashboard、机器人动作、摄像头理解、本地音乐、单手姿态交互和柴火基地车
日记检索。

## 运行环境

- Python：固定为 `3.10`，项目声明范围为 `>=3.10,<3.11`
- 包管理器：`uv`
- PC：当前部署环境为 x86_64 Ubuntu，可连接 Reachy Mini，也可独立运行
- Jetson：JetPack 6.2 / CUDA 12.6，使用系统 Python 和 TensorRT
- Dashboard：默认监听 `0.0.0.0:8640`
- Reachy daemon：硬件模式下由程序自动管理，默认端口 `8000`

项目中的目标名仍使用 `mac` 和 `jetson`。PC 启动脚本使用 `--target mac`，这里的
`mac` 表示桌面直连模式，也用于当前 Ubuntu PC 部署。

## 仓库不包含的文件

以下内容体积大、包含本机状态或包含凭据，不提交到 Git：

- `.env`、`.env.*`：API Key 和设备配置，保留 `.env.example`
- `.venv/`：本地 Python 虚拟环境
- `models/`：KWS、VAD、ONNX、TensorRT、Core ML 等模型制品
- `data/`：日记正文、图片、Chroma 向量库和运行期数据
- `state/`：PID、日志和 daemon 状态
- QQ 音乐加密容器及历史开场白备份

首次部署后需要按下文下载模型、同步日记或在目标设备上构建 TensorRT engine。

## 快速部署：Ubuntu PC

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y \
  python3.10 python3.10-venv python3.10-dev \
  build-essential pkg-config \
  libasound2-dev portaudio19-dev ffmpeg \
  python3-gi curl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

重新打开终端，确认 `uv --version` 可用。

### 2. 拉取代码并创建环境

```bash
git clone git@github.com:jjjadand/reachy-mini_chaihuo.git
cd reachy-mini_chaihuo

uv venv --python /usr/bin/python3.10 --system-site-packages .venv
UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  uv sync --extra dev --no-install-package pygobject
```

### 3. 配置环境变量

```bash
cp .env.example .env
chmod 600 .env
```

至少填写：

```dotenv
BAILIAN_API_KEY=你的百炼_API_Key
BAILIAN_WORKSPACE_ID=你的工作空间_ID
REACHY_TARGET=mac
```

如需高德定位，填写 `AMAP_WEB_KEY`；启用数字签名时同时填写
`AMAP_WEB_PRIVATE_KEY`。其他音频、视觉、唤醒词和手势参数参考 `.env.example`。

### 4. 下载本地语音模型

```bash
.venv/bin/python scripts/download_kws_model.py
.venv/bin/python scripts/download_vad_model.py
```

模型下载到 `models/`，不会加入 Git。

### 5. 启动

```bash
./start-pc.sh
```

打开 `http://127.0.0.1:8640/`。局域网设备可访问
`http://<PC-IP>:8640/`。

- 检测到 `/dev/ttyACM0`：启动 Reachy Mini 硬件模式
- 未检测到 `/dev/ttyACM0`：自动添加 `--standalone`，仅使用 PC 音视频设备

也可以直接运行：

```bash
.venv/bin/chaihuo-reachy dashboard --target mac --standalone
```

## 快速部署：Jetson

Jetson 的 TensorRT Python 绑定来自 JetPack 系统环境，因此虚拟环境必须启用
`--system-site-packages`。

```bash
git clone git@github.com:jjjadand/reachy-mini_chaihuo.git
cd reachy-mini_chaihuo

uv venv --python /usr/bin/python3.10 --system-site-packages .venv
UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ uv sync --extra jetson

cp .env.example .env
chmod 600 .env
```

在 `.env` 中至少配置：

```dotenv
BAILIAN_API_KEY=你的百炼_API_Key
BAILIAN_WORKSPACE_ID=你的工作空间_ID
REACHY_TARGET=jetson
REACHY_CAMERA_DEVICE=auto
```

启动并检查服务：

```bash
./reachy-service.sh start --target jetson
./reachy-service.sh status
./reachy-service.sh logs
```

安全停止：

```bash
./reachy-service.sh stop
```

停止流程会先让机器人休眠，再关闭 Dashboard、媒体资源和本项目启动的 daemon。

## 手势模型部署

手势功能默认不会随仓库提供模型。先准备 NVIDIA `trt_pose_hand` 对应的
`hand_pose_resnet18_baseline_att_224x224.pth`，再导出公共制品：

```bash
.venv/bin/python scripts/export_hand_pose_models.py \
  --weights /path/to/hand_pose_resnet18_baseline_att_224x224.pth
```

Jetson 的 TensorRT engine 必须在目标设备上按当前 JetPack/TensorRT 版本构建：

```bash
.venv/bin/python scripts/build_hand_pose_tensorrt.py \
  --onnx models/hand_pose/hand_pose_resnet18.onnx \
  --engine models/hand_pose/hand_pose_resnet18_fp16.engine

.venv/bin/python scripts/verify_hand_pose_jetson.py \
  --engine models/hand_pose/hand_pose_resnet18_fp16.engine
```

PC 不能直接复用 Jetson 生成的 TensorRT engine。模型缺失时可保持手势功能关闭，
不影响基础语音、Dashboard、摄像头和日记检索。

## 日记数据部署

日记正文、图片和 Chroma 索引保存在 `data/`，不会提交到仓库。

完整同步并重建索引：

```bash
.venv/bin/chaihuo-reachy index-journals
```

增量同步：

```bash
.venv/bin/chaihuo-reachy sync-journals
```

Jetson 可安装仓库中的 systemd 定时任务。服务文件默认用户和目录为
`recomputer`、`/home/recomputer/chaihuo_reachy`；如实际路径不同，先编辑
`deploy/chaihuo-journal-sync.service`。

```bash
sudo cp deploy/chaihuo-journal-sync.service /etc/systemd/system/
sudo cp deploy/chaihuo-journal-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chaihuo-journal-sync.timer
systemctl status chaihuo-journal-sync.timer
```

## 本地音乐与开场白

- 当前开场白：`assets/opening/chaihuo_opening_zh.wav`
- 重新生成：`.venv/bin/python scripts/generate_opening_audio.py`
- 将合法的 MP3、FLAC、WAV、M4A、AAC、OGG 或 Opus 放入 `bgm/` 后运行：

```bash
.venv/bin/python scripts/convert_bgm.py
```

转换结果保存在 `bgm/compatible/`。QQ 音乐 `.mgg`、`.mflac` 等加密容器不能由
该脚本直接转换，应使用合法来源的标准音频文件。

## 常用命令

```bash
# Web Dashboard（默认命令）
.venv/bin/chaihuo-reachy dashboard

# 纯语音循环
.venv/bin/chaihuo-reachy run

# 硬件诊断
.venv/bin/chaihuo-reachy test -v

# 关闭唤醒词
.venv/bin/chaihuo-reachy dashboard --no-wake-word

# 指定唤醒引擎：local / cloud / off
.venv/bin/chaihuo-reachy dashboard --wake-engine local

# 运行测试
.venv/bin/pytest -q
```

## 故障排查

- `BAILIAN_API_KEY 未设置`：检查项目根目录 `.env`，并确认权限为 `600`
- 找不到 `.venv`：重新执行对应平台的 `uv venv` 和 `uv sync`
- 找不到机器人：检查 USB 数据线、电源和 `/dev/ttyACM0`
- PC 无声音：检查默认 ALSA/PulseAudio 设备和 `portaudio19-dev`
- Dashboard 未就绪：运行 `./reachy-service.sh logs` 查看初始化日志
- TensorRT engine 无法加载：必须在当前 Jetson 上重新构建，不要复制其他设备制品
- 端口占用：检查 `8000`（daemon）和 `8640`（Dashboard），不要按端口误杀未知进程

## 项目结构

```text
src/chaihuo_reachy/   核心应用、Dashboard、音视频和机器人控制
scripts/              模型下载、导出、验证和媒体处理脚本
deploy/               日记同步 systemd 单元
tests/                自动化测试
assets/               开场白等必要静态资源
music/                内置舞蹈音乐
bgm/compatible/       Dashboard 可播放的兼容音频
```

## License

MIT
