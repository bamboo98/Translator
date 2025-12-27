# VR翻译器

一款支持SteamVR掌心字幕显示的实时语音翻译软件。通过捕获桌面音频，使用Vosk进行本地语音识别，调用在线翻译API获取翻译结果，并在SteamVR中显示掌心字幕。

## 功能特性

- 🎤 **桌面音频捕获**: 使用Windows WASAPI Loopback捕获系统音频
- 🗣️ **本地语音识别**: 基于Vosk离线语音识别，支持多语言
- 🌐 **在线翻译**: 支持硅基流动等在线翻译API
- 🥽 **VR字幕显示**: 通过OpenXR在SteamVR掌心显示翻译字幕
- 🖥️ **桌面窗口**: PyQt6图形界面，实时显示识别和翻译结果

## 系统要求

- Windows 10/11
- Python 3.9+
- SteamVR（用于VR显示功能）
- 支持OpenXR的VR设备（可选）

## 安装步骤

### 1. 克隆或下载项目

```bash
git clone <repository-url>
cd 翻译器
```

### 2. 安装Python依赖

```bash
pip install -r requirements.txt
```

**注意**: 在Windows上安装`pyaudio`可能需要预编译的wheel文件。如果安装失败，可以尝试：

```bash
pip install pipwin
pipwin install pyaudio
```

或者使用conda：

```bash
conda install pyaudio
```

### 3. 下载Vosk语音识别模型

Vosk需要下载对应语言的模型文件。访问 [Vosk模型下载页面](https://alphacephei.com/vosk/models) 下载所需语言的模型。

**推荐模型**:
- 中文: `vosk-model-small-cn-0.22` (约40MB)
- 英文: `vosk-model-small-en-us-0.15` (约40MB)
- 日文: `vosk-model-small-ja-0.22` (约40MB)

**下载后**:
1. 解压模型文件
2. 将解压后的文件夹放到项目的 `models/` 目录下
3. 确保文件夹名称包含语言代码（如 `vosk-model-small-cn-0.22`）

示例目录结构：
```
翻译器/
├── models/
│   ├── vosk-model-small-cn-0.22/
│   ├── vosk-model-small-en-us-0.15/
│   └── ...
```

### 4. 配置API密钥

编辑 `config.json` 文件（首次运行会自动创建），设置翻译API密钥：

```json
{
  "translation": {
    "api_provider": "siliconflow",
    "api_key": "your-api-key-here",
    "api_url": "https://api.siliconflow.cn/v1/chat/completions",
    "model": "deepseek-chat",
    "target_language": "zh"
  }
}
```

**获取API密钥**:
- 硅基流动: 访问 [硅基流动官网](https://siliconflow.cn) 注册并获取API密钥
- 其他API: 根据相应服务提供商的文档获取

## 使用方法

### 启动程序

```bash
python main.py
```

### 基本操作

1. **选择识别语言**: 在控制面板中选择要识别的语言（需要已下载对应模型）
2. **配置API**: 确保已设置正确的API密钥
3. **检查VR状态**: 如果使用VR功能，确保SteamVR已启动且设备已连接
4. **点击"开始"**: 开始捕获音频并进行识别翻译
5. **查看结果**: 
   - 识别文本显示在左侧面板
   - 翻译结果显示在右侧面板
   - VR用户可在掌心看到翻译字幕

### 停止程序

点击"停止"按钮或直接关闭窗口。

## 配置说明

### 配置文件

程序首次运行会创建 `config.json` 配置文件。主要配置项：

#### 音频配置
```json
"audio": {
  "sample_rate": 16000,    // 采样率（Hz）
  "channels": 1,            // 声道数
  "chunk_size": 4000,       // 每次读取的帧数
  "format": "int16"         // 音频格式
}
```

#### Vosk配置
```json
"vosk": {
  "model_path": "models",   // 模型存放目录
  "language": "zh",         // 默认语言
  "available_languages": {  // 可用语言列表
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어"
  }
}
```

#### 翻译配置
```json
"translation": {
  "api_provider": "siliconflow",  // API提供商
  "api_key": "",                   // API密钥
  "api_url": "",                   // API地址
  "model": "deepseek-chat",        // 模型名称
  "source_language": "auto",      // 源语言（auto为自动检测）
  "target_language": "zh",         // 目标语言
  "timeout": 30                    // 请求超时（秒）
}
```

#### VR配置
```json
"vr": {
  "enabled": true,              // 是否启用VR功能
  "overlay_width": 512,         // Overlay宽度（像素）
  "overlay_height": 256,        // Overlay高度（像素）
  "font_size": 24,              // 字体大小
  "text_color": [255, 255, 255, 255],      // 文本颜色 RGBA
  "background_color": [0, 0, 0, 200]       // 背景颜色 RGBA
}
```

## 故障排除

### 音频捕获问题

**问题**: 无法捕获系统音频

**解决方案**:
1. 确保使用Windows系统（WASAPI Loopback仅支持Windows）
2. 检查音频设备是否正常工作
3. 尝试以管理员权限运行程序
4. 如果找不到Loopback设备，程序会尝试使用默认输出设备

### Vosk模型问题

**问题**: 提示找不到语言模型

**解决方案**:
1. 确认模型已下载到 `models/` 目录
2. 检查模型文件夹名称是否正确
3. 确保模型文件完整（未损坏）
4. 查看控制台输出的详细错误信息

### 翻译API问题

**问题**: 翻译失败或超时

**解决方案**:
1. 检查API密钥是否正确
2. 确认网络连接正常
3. 检查API地址是否正确
4. 查看控制台输出的错误信息
5. 尝试增加超时时间

### VR显示问题

**问题**: VR字幕不显示

**解决方案**:
1. 确保SteamVR已启动
2. 检查VR设备是否已连接
3. 确认OpenXR运行时已安装
4. 查看程序状态栏的VR连接状态
5. 如果不需要VR功能，可以在配置中设置 `"enabled": false`

### PyAudio安装问题

**问题**: pip install pyaudio 失败

**解决方案**:
1. 使用预编译的wheel文件:
   ```bash
   pip install https://download.lfd.uci.edu/pythonlibs/archived/PyAudio-0.2.11-cp39-cp39-win_amd64.whl
   ```
   (根据Python版本调整)
2. 使用conda安装
3. 使用pipwin安装

## 技术架构

- **音频捕获**: PyAudio + Windows WASAPI Loopback
- **语音识别**: Vosk (离线本地识别)
- **翻译服务**: 硅基流动等在线API
- **VR显示**: OpenXR (pyopenxr)
- **GUI框架**: PyQt6
- **异步处理**: threading + asyncio

## 开发计划

- [x] 音频捕获模块
- [x] Vosk语音识别集成
- [x] 翻译API客户端
- [x] OpenXR VR显示
- [x] PyQt6桌面界面
- [x] 主程序整合
- [ ] 手部追踪集成（精确定位掌心位置）
- [ ] 更多翻译API支持
- [ ] 音频预处理优化
- [ ] 配置文件GUI编辑器

## 许可证

[待定]

## 贡献

欢迎提交Issue和Pull Request！

## 联系方式

如有问题或建议，请通过Issue反馈。


