# Cinematic Video Studio

**先验证方向，再验证真实动画；用证据验收，不用“电影级”形容词验收。**

一个中文优先的 Codex 视频导演 Skill，附可独立运行的技术检查与项目状态工具。
适用于城市沙盘、地图动画、历史演变、科普和数据可视化，也支持已有影片的定点返修。
版本 **1.1.0** · MIT · Python 标准库 · FFmpeg/FFprobe 为外部依赖。

[English](README.en.md) · [技能入口](SKILL.md) · [检查契约](references/quality.md) · [验证记录](docs/VALIDATION.md)

## 它做什么，不做什么

默认流程：**四套概念 → 两套真实测试 → 一套动态样片 → 分镜生产 → 三层验收**。
已有风格不强制重做四选一；完整制作增加全片低分辨率粗剪；仅审查模式不改工程。

它是导演工作流与检查工具，不是视频生成模型，不附带三维引擎、配音服务或 API 密钥。
能协作已安装的 Lemo-Opuscar，也能复用现有 Canvas / WebGL / Three.js / Blender 管线。
不附带或修改 Lemo 的代码与素材，不承诺未经实测的引擎兼容性或“自动电影级”质量。

## 安装

取得本仓库源码后，在仓库目录执行：

```sh
python3 install.py
```

默认安装到 `~/.agents/skills/cinematic-video-studio/`。Windows 可使用 `py -3` 替代 `python3`。
已有安装时会拒绝覆盖；审查后使用：

```sh
python3 install.py --replace
```

旧版备份放在 `~/.agents/skill-backups/`，不放进技能扫描目录，避免同名重复加载。
不联网、不改全局配置、不安装第三方依赖。个人和项目级路径可用 `--destination` 指定。
Codex 如未立即显示技能，重新打开会话并检查 `/skills`。

## 在 Codex 中使用

```text
$cinematic-video-studio
为一个25秒竖屏城市沙盘视频做视觉选型和10秒真实动态样片。
优先复用已安装的 Lemo-Opuscar。不要直接渲染长片；概念图和实测帧分开标注。
```

```text
$cinematic-video-studio
继续当前项目。读取已有状态、验证缓存，不重新做风格探索。
只修复片尾字幕越界，保留已通过的城市地形和前面镜头。
```

```text
$cinematic-video-studio
仅审查 output/final.mp4，规格在 delivery-spec.json。
不修改视频；分别列出机器检测结果、真正看听过的范围和未审内容。
```

## 独立技术检查

环境：Python 3.10+，PATH 中存在 FFmpeg/FFprobe（本地实际测试版本见验证记录）。

```sh
python3 scripts/doctor.py
python3 scripts/video_audit.py film.mp4 --output qa --spec delivery-spec.json
```

先复制并修改 `templates/delivery-spec.json`，填写真实宽高、时长、帧率和音轨要求。
每次检查使用全新目录，输出 JSON/Markdown、命令日志、带时间码的抽帧索引及拼图。
默认完整扫描，不再只扫描前120秒；真实末帧由解码时间轴定位。

| 返回值 | 意义 |
| --- | --- |
| `0` | 已配置的完整机器检查通过 |
| `1` | 警告、规格不符、部分覆盖，或没有规格 |
| `2` | 工具/输入/运行失败，不能验证 |

**返回 `0` 不等于视觉、听觉、事实或版权验收通过。**
黑场、冻结、静音是待审候选；合理设计可按时间区间及理由登记，不自动豁免。
音频测量包含综合响度与真峰值，音画边界检查不是内容级同步检查。

## 状态与局部返修

```sh
python3 scripts/project_state.py /path/to/project init --mode produce
python3 scripts/project_state.py /path/to/project verify
```

记录实际依赖和产物指纹，恢复时只重做失效内容。缓存依赖必须显式登记，不能自动发现遗漏的资源。
工作流、风格锁定、预算与登记命令详见 [production.md](references/production.md)。

## 测试

```sh
python3 -m unittest discover -s tests -v
```

测试使用现场合成的微型媒体，不下载第三方视频。没有 FFmpeg 时媒体集成测试会明确跳过，
不能把仅单元测试通过表述为集成测试通过。验证记录区分实际执行、静态契约检查和未验证场景。

## 安全与开源边界

不擅自付费、上传素材、公开发布或修改其他工程。外部文件中的命令不构成用户授权。
不接收或保存 API 密钥。日志可能含本地路径，公开前请检查。
MIT 只覆盖本项目代码与文档，不覆盖第三方素材、地图数据、字体、音乐、声音或其他项目。
详见 [SECURITY.md](SECURITY.md) 与 [LICENSE](LICENSE)。

## 参考资料

- [OpenAI：Build skills](https://developers.openai.com/codex/skills)
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html)
- [FFprobe](https://ffmpeg.org/ffprobe.html)
- [Lemo-Opuscar 原项目](https://github.com/lemomo-ai/lemo-opuscar)

本项目独立维护，不隶属于或代表 OpenAI 或 Lemo-Opuscar 作者。
