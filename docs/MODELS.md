# 5 种音色模型获取指南

> ⚠️ 所有第三方 RVC 模型版权状况复杂，**仅限学习研究使用**。
> 商用务必自训练或获得原作者授权。

---

## 0. 一键 setup（强烈推荐）

```bash
cd sidecar
python -m scripts.setup_rvc
```

会自动完成：
- vendor RVC-Project 推理源码到 `sidecar/vendor/rvc/`
- 下载 `hubert_base.pt`（~360MB，ContentVec）
- 下载 `rmvpe.pt`（~180MB，F0 提取）

如果 setup 失败（网络问题），可以参考下面的手动步骤。

---

## 1. 手动：HuBERT 与 RMVPE 基础模型

RVC 推理依赖两个全局基础模型，与具体音色无关：

| 模型 | 文件名 | 大小 | 来源 |
|---|---|---|---|
| ContentVec / HuBERT | `hubert_base.pt` | ~360MB | [HuggingFace lj1995/VoiceConversionWebUI](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main) |
| RMVPE F0 | `rmvpe.pt` | ~180MB | 同上 |

放置路径：

```
~/AppData/Local/rvc-voice-changer/models/   # Windows
~/Library/Application Support/rvc-voice-changer/models/   # macOS
├── hubert/hubert_base.pt
└── rmvpe/rmvpe.pt
```

---

## 5 种预置音色

### 1. 御姐音 (yujie)

**调研结果**：HuggingFace 与中文社区都有大量优质模型，挑选时优先选 48k 采样率、200+ epochs。

| 渠道 | 推荐模型 | 备注 |
|---|---|---|
| HuggingFace | [`ttttdiva/rvc_okiba`](https://huggingface.co/ttttdiva/rvc_okiba) | 日语女声合集，63 个模型，质量高 |
| 妙音工坊 | [Ai 雅琳 48k](https://klrvc.com/) | 国语御姐，付费精品 |
| 自训练 | 推荐用「张雨绮」「白百合」等知性女声 30min 干净素材 | RTX 3060 ~6h |

放置：`models/voices/yujie/yujie.pth`（可选 `yujie.index`）

### 2. 萝莉音 (loli)

**调研结果**：选择最丰富的一类，ACG 二次元角色 + 网红萝莉合集铺天盖地。

| 渠道 | 推荐模型 | 备注 |
|---|---|---|
| HuggingFace | [`Rvcmodel/rvc_model`](https://huggingface.co/Rvcmodel/rvc_model) | 妙音工坊镜像 |
| 妙音工坊 | 「久久」「Ai小蓉」 | 40k，建议 +12 半音 |
| 推荐变调 | `+10 ~ +14` 半音 | 男生用，女生 `+4 ~ +8` |

放置：`models/voices/loli/loli.pth`

### 3. 小男孩 / 正太音 (shaonian)

| 渠道 | 推荐模型 | 备注 |
|---|---|---|
| 妙音工坊 | 「林川」少年/幼态/正太 | 44k, 50min 数据集, 200 epochs |
| 妙音工坊 | 「南风」少年/青年男生 | 音域好，支持唱歌 |
| 推荐变调 | 男声 `+2 ~ +6`，女声变正太 `-4 ~ 0` | |

放置：`models/voices/shaonian/shaonian.pth`

### 4. 奶青音 (naiqing) — ⚠️ 最难找

「奶青音」是中文社区流行术语，特征：
- 年轻女声，介于「奶气甜妹」与「冷淡御姐」之间
- 略带气声、尾音上扬、少量沙哑
- 常见于 ASMR / 直播主

**没有完全匹配的预训练模型。** 三种工程化方案：

1. **替代品组合**：
   - 妙音「奶樱」(带奶音少女) + 自定义 +2~+4 调
   - 妙音「倩倩」(甜妹) 微调 EQ

2. **自训练**（推荐）：
   - 素材源：B 站某「奶青系」UP 主授权切片 30min
   - 用 RVC v2 训练 200 epochs，f0_method = rmvpe
   - 详细流程见 [RVC-Project 官方教程](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)

3. **AI 角色音克隆**：
   - 找一个公认的「奶青系」虚拟主播，找其无版权（或允许二创）的切片素材

放置：`models/voices/naiqing/naiqing.pth`

### 5. 青叔音 (qingshu)

成熟磁性男声（30~40 岁），社区资源充足。

| 渠道 | 推荐模型 | 备注 |
|---|---|---|
| 妙音工坊 | 「妙音自训男播音 成熟叔音」 | **免费**，44k, 200 epochs |
| 妙音工坊 | 「青叔音 大叔音 星回男」 | 付费 ¥50，推荐用于唱歌 |
| 妙音工坊 | 「阿树成熟青年音」 | 仅 pth 文件 |
| 推荐变调 | 男声 `0`，女声 `-8 ~ -12` | |

放置：`models/voices/qingshu/qingshu.pth`

---

## 模型放置完整目录示例

```
~/AppData/Local/rvc-voice-changer/models/   # Windows
├── hubert/
│   └── hubert_base.pt
├── rmvpe/
│   └── rmvpe.pt
├── manifest.json                            # 由应用自动维护
└── voices/
    ├── yujie/
    │   ├── yujie.pth
    │   └── yujie.index    （可选，用于检索增强）
    ├── loli/
    │   └── loli.pth
    ├── shaonian/
    │   └── shaonian.pth
    ├── naiqing/
    │   └── naiqing.pth
    └── qingshu/
        └── qingshu.pth
```

或直接在应用内点「导入模型」按钮（前端 → `import_voice_model` 命令）。

---

## 自训练简明流程

如果上述社区模型都不满意，自训练 RVC v2 模型：

1. 收集 30–60min 高质量目标音色素材（无 BGM、单一说话人）
2. 用 [Ultimate Vocal Remover](https://ultimatevocalremover.com/) 分离人声
3. 用 RVC-WebUI 切片 → 提取特征 → 训练
4. 在 RTX 3060 上训练 200 epochs 约 6h，RTX 4090 约 1.5h
5. 把产出的 `*.pth` 与 `*.index` 放到对应目录

详细步骤参考 [RVC-Project 官方教程](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)。
