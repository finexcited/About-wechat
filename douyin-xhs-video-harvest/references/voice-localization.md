# 中文人声删除与目标语言配音

只在视频已通过无水印、9:16、短边 ≥1080 的初检，且用户已选择删除人声或生成目标语言配音时读取本文件。

## 1. 确认原语音

先提取独立音轨并转写对白。以可辨识的连续中文对白、旁白或口播作为语音处理条件，字幕只用于交叉核对。

```bash
ffmpeg -i input.mp4 -vn -ac 2 -ar 44100 -c:a pcm_s16le source.wav
```

记录原文、逐句起止时间和不确定词。若无法可靠转写，明确报告并停止 AI 翻译，不要编造台词。

## 2. 分离人声与背景

使用本机可用的音源分离工具，优先 Demucs：

```bash
uvx --with numpy --from demucs demucs \
  -n htdemucs --two-stems=vocals -d cpu \
  -o stems source.wav
```

从 `stems/htdemucs/source/` 取得：

- `vocals.wav`：原语言人声，仅用于核验或后续清理。
- `no_vocals.wav`：保留的背景音乐、环境声和非人声内容。

两轨时长必须与原音轨一致。分离失败时停止，不要用简单的音量衰减冒充人声分离。

## 3. 导出无人声版

保留原视频画面，仅用背景轨替换音频：

```bash
ffmpeg -i input.mp4 -i no_vocals.wav \
  -map 0:v:0 -map 1:a:0 \
  -c:v copy -c:a aac -b:a 192k \
  -map_metadata -1 -map_metadata:s:v -1 -map_metadata:s:a -1 \
  -fflags +bitexact -flags:v +bitexact -flags:a +bitexact \
  -movflags +faststart output_no_voice.mp4
```

抽查开头、中段和结尾，确认原语言对白已消失且背景音连续。

## 4. 生成目标语言配音

1. 根据原对白生成目标语言译文，保留时长允许时不要删减关键信息。
2. 按原句时间窗拆分配音。每句起始、结束均不得超出所属画面段落；必要时优先精简译文，再小幅调整语速。
3. 使用目标语言的 TTS/AI 配音，逐句导出独立音频并测量时长。
4. 将目标语言人声放置到对应时间点，与 `no_vocals.wav` 混合；不要保留原语言人声。
5. 对白应清晰高于背景音，同时避免削波。常见起始设置是背景约 `0.65`、配音约 `1.3–1.5` 倍增益，再用最终限幅器修正；必须按实际响度调整。

混音后先导出 WAV，确认时间轴、句间留白和响度，再与视频组合：

```bash
ffmpeg -i input.mp4 -i dubbed_mix.wav \
  -map 0:v:0 -map 1:a:0 \
  -c:v copy -c:a aac -b:a 192k \
  -map_metadata -1 -map_metadata:s:v -1 -map_metadata:s:a -1 \
  -fflags +bitexact -flags:v +bitexact -flags:a +bitexact \
  -movflags +faststart output_dub-ja.mp4
```

按目标语言替换文件后缀，例如 `ja`、`en`、`ko`。

## 5. 验收

- `ffprobe` 可正常读取。
- 视频完整解码无错误。
- 画面分辨率、帧率、时长与清理后原片一致。
- 无人声版没有可辨识的原语言对白。
- 配音版的目标语言对白逐句落在对应时段，无截断或重叠，背景音仍在。
- 音频无削波，人声清楚高于背景。
- 再次运行 `media_guard.py clean`，随后运行 `media_guard.py inspect <file> --require-clean`。
- 如果画面仍有原语言硬字幕，最终回复中明确说明字幕未替换或未删除。
