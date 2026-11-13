# 制作状态、缓存与预算

## 真相来源

项目已有简报/TREATMENT 与时间轴优先；不复制相互矛盾的配置。
`PROJECT_STATE.json` 保存阶段、模式、已选方向、预算、关卡、产物、问题和下一步。
它是本地工程状态，不是对话记忆、后台执行器，也不是账号额度监控器。

## 最小项目结构

```text
project/
  TREATMENT.md 或 PROJECT_BRIEF.md
  PROJECT_STATE.json
  delivery-spec.json
  STYLE_LOCK.md
  shots.json
  src/ assets/ environment.json
  preproduction/ animatic/ prototype/ output/ qa/
```

按任务需要建目录；仅审查模式不要求建立完整制作工程。
镜头表至少含 id、start_frame、end_frame（建议左闭右开）、目的、运动、旁白、字幕与音效。
使用有理帧率时保持统一换算规则，避免逐段舍入累积误差。

## 状态使用

```sh
python3 <skill>/scripts/project_state.py <project> init --mode produce
python3 <skill>/scripts/project_state.py <project> show
python3 <skill>/scripts/project_state.py <project> record --key shot-01 \
  --input src/shot-01.js --input assets/map.json --input STYLE_LOCK.md \
  --input environment.json --input render-config.json --input package-lock.json \
  --output output/shot-01.mp4 --seed 42
python3 <skill>/scripts/project_state.py <project> verify
```

路径相对项目；不能登记越出项目的路径或指向外部的符号链接。
所有实际依赖都要登记：源码、资源、参数、锁文件、风格锁及环境版本文件。
缓存工具不会自动发现依赖、验证环境清单是否真实，或与远端资源重新同步。
记录时输出已经存在；SHA-256 指纹绑定输入和输出。
`verify` 只比较**当前登记的文件**，不是动画内容审查，也不批准质量。
改变种子需更新参数文件并重渲染，不能单改状态中的种子字段来伪造有效缓存。

## 失效规则

- 改字幕/字形：重做受影响文字及合成，未受影响的地形可保留。
- 改材质、灯光或相机：受影响镜头需重新渲染及视审。
- 改音轨：重新混音、检查时间边界、响度和听审；视觉缓存可能保留。
- 改事实来源或授权：重新核验受影响内容，技术通过不能抵消事实问题。
- 代码、依赖版本、环境或输入证据缺失：不能仅凭文件存在沿用缓存。

工具用独占锁和原子替换保护写入。并发代理不共享同一可写状态；由一个协调者合并。
锁残留时先确认没有活跃写入，再恢复，不自动删除锁。

## 预算与阶段关卡

默认概念方向 4、真实候选 2、动态样片 1、每问题返修 2 轮。
先低分辨率、再高分辨率；不把低分辨率预览误记为目标规格验收。
记录已用次数和剩余额度（不知道账号额度就写 unknown）。预算是约束，不是必须消耗完的目标。

A：选型有真实帧、风险可控、风格锁存在。
B：全片粗剪按需完成，关键动态样片经过实际复核。
C：机器规格与必需的视听/事实/授权审查完成，无未解决 P0/P1。
`blocked`、`partial`、`not_checked` 是有效状态；不为了走流程伪造 pass。
