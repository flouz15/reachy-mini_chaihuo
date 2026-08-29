# PC 运行说明

项目已从 Jetson 迁移到本机 x86_64 Ubuntu，运行环境固定为 Python 3.10。

## 启动

```bash
cd /home/darklee/chaihuo_reachy
./start-pc.sh
```

然后打开 `http://127.0.0.1:8640/`。局域网其他设备可使用这台 PC 的 IP 和端口 `8640`。

未检测到 `/dev/ttyACM0` 时，脚本自动添加 `--standalone`。Reachy Mini 通过 USB 接入 PC 后，脚本使用 `/dev/ttyACM0` 启动本地 Reachy daemon，并继续使用直连摄像头和音频。

## 活动开场白

Dashboard 的“活动开场”按钮播放 `assets/opening/chaihuo_opening_zh.wav`。音频已预先生成，正式播放不需要联网；播放期间会暂停唤醒词、ASR、聊天、手势和舞蹈，并配合轻微的说话、天线与身体动作。

需要修改文案并重新生成素材时：

```bash
cd /home/darklee/chaihuo_reachy
.venv/bin/python scripts/generate_opening_audio.py
```

## 本地 BGM

Dashboard 可以从 `bgm/compatible` 选择本地音乐，也可以在对话框输入“播放音乐”、
“播放音乐 + 歌名”或“关闭音乐”。音乐播放期间会暂停 ASR 和其他交互，停止或自然
播放完毕后自动恢复。

将标准 MP3、FLAC、WAV、M4A、AAC、OGG 或 Opus 文件放入 `bgm` 后执行：

```bash
cd /home/darklee/chaihuo_reachy
.venv/bin/python scripts/convert_bgm.py
```

脚本会生成 Reachy Mini 更兼容的 24 kHz、16-bit、单声道 PCM WAV。QQ 音乐的
`.mgg`、`.mflac` 等加密容器不是标准音频，需先从合法来源取得未加密音频文件。

## 重建环境

系统已安装 `python3-gi`、ALSA、PortAudio 和 FFmpeg。虚拟环境需要读取系统的 GI 包：

```bash
cd /home/darklee/chaihuo_reachy
rm -rf .venv
uv venv --python /usr/bin/python3.10 --system-site-packages .venv
UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  uv sync --extra dev --no-install-package pygobject
```

## 配置

- PC 配置：`.env`
- Jetson 原配置备份：`.env.jetson`
- PC 默认音频：PulseAudio/ALSA `default`
- PC 默认摄像头：`/dev/video0`
- 云端凭据只保存在权限为 `600` 的环境文件中。

手势后端的 Jetson TensorRT engine 不能直接用于 RTX PC。基础语音、摄像头、Dashboard、日记检索与云端模型可正常运行；PC 手势推理需要另行导出兼容 RTX/TensorRT 的 engine。
