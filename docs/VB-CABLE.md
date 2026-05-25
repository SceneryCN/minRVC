# VB-Cable / BlackHole 安装指南

虚拟声卡是把变声后的音频「假装成麦克风输入」送给 OBS / StudioOne 的关键。

## Windows：VB-Cable

1. 下载：https://vb-audio.com/Cable/
2. 解压后右键 `VBCABLE_Setup_x64.exe` → 「以管理员身份运行」
3. 重启电脑
4. 安装后系统会出现两个新设备：
   - **CABLE Input** （扬声器/输出端）→ 我们把变声后的音频送给它
   - **CABLE Output** （麦克风/输入端）→ OBS 把它当作麦克风读取

> 一个 VB-Cable 实例只支持一组送/收。如果还想自己监听，需要再装
> [VB-Cable A+B](https://vb-audio.com/Cable/index.htm#DownloadCable) 或 VoiceMeeter Banana。

## macOS：BlackHole

1. `brew install blackhole-2ch` 或下载 https://existential.audio/blackhole/
2. 重启
3. 系统会出现 `BlackHole 2ch`，**它既是输出也是输入**：
   - 在「声变」里输出选 `BlackHole 2ch`
   - 在 OBS 里麦克风源选 `BlackHole 2ch`

## 验证

启动「声变」后：
- 应用顶部应显示绿色提示「已识别虚拟声卡：CABLE Input ...」
- 输出 VU 表能看到电平跳动 → 表明音频在送给虚拟声卡

如果显示橙色警告「未检测到虚拟声卡」，请确认：
- 驱动已安装（设备管理器 → 声音、视频和游戏控制器）
- 重启系统
- 在「声变」设备选择中手动指定 `CABLE Input`
