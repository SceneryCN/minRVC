# StudioOne / OBS 直播链路配置

## 完整音频链路

```
[物理麦克风] ─► 「声变」捕获
                ├─ Rust cpal 采集
                ├─ Python RVC 推理（御姐/萝莉/...）
                └─ Rust cpal 输出 ──► [CABLE Input] (虚拟声卡)
                                            │
                                            ▼
                                     [CABLE Output] ◄ 直播软件读取
                                            │
                                            ▼
                          ┌─────────────────────────────┐
                          │  OBS / StudioOne / 抖音直播伴侣 │
                          │  (混音 / EQ / 压限 / 推流)   │
                          └─────────────────────────────┘
```

## OBS 配置

1. 设置 → 音频 → **麦克风/辅助音频**：选 `CABLE Output (VB-Audio Virtual Cable)`
2. 取消勾选系统默认麦克风（避免双路重复）
3. 在主界面音频混音器里看到 CABLE Output 通道有电平跳动 → 成功

### 推荐滤镜（按顺序）

1. **噪声门限** - threshold -45dB / hold 200ms
2. **降噪** - RNNoise（OBS 内置）
3. **压缩器** - ratio 4:1 / threshold -22dB / attack 5ms / release 60ms
4. **限制器** - threshold -2dB

## StudioOne 配置

1. 选项 → 音频设置 → 设备
   - 输入：`CABLE Output (VB-Audio Virtual Cable)`
   - 输出：你真正的扬声器/耳机
2. 新建「instrument track」或「mono audio track」，输入选 `CABLE Output`
3. 在通道条加入 EQ / Compressor / Limiter / Reverb 等
4. 主输出送到耳机或推流软件

> StudioOne 的 ASIO 需要单独驱动。如果遇到不兼容，
> 可装 [ASIO4ALL](http://www.asio4all.org/) 把 WASAPI 包装成 ASIO。

## 常见问题

**Q: 我自己听不到自己变声后的声音？**

A: 因为 CABLE Input 是虚拟扬声器，物理上不出声。两种解决：

- 在 OBS 里「监控」选「监控并输出」+ 监听设备选物理耳机
- 或在 Windows 声音控制面板 → 录制 → CABLE Output → 属性 → 侦听 → 「侦听此设备」

**Q: 延迟太大（>300ms）？**

A: 在「声变」里把 chunk_size 调小（默认 1024 → 512），但太小会让 GPU 推理跟不上。
也可在系统声音控制面板把 CABLE 设备的「位深与采样率」改为 48000Hz / 16bit。

**Q: 直播软件听到的声音有「咔哒」声？**

A: 多半是 SOLA 拼接没对齐。在「声变」UI 里：
- 重启引擎
- 增大 latency_secs（前端 → Rust → engine 的 StartConfig）
- 检查麦克风采样率与输出采样率是否一致（理想都 48k）
