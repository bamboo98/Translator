"""
使用sounddevice库的音频捕获模块
sounddevice对Windows WASAPI Loopback有更好的支持
"""
import sounddevice as sd
import threading
import queue
import numpy as np
from typing import Optional, Callable
from src.audio.processor import AudioProcessor

class AudioCapture:
    """音频捕获类，使用sounddevice捕获系统音频"""
    
    def __init__(self, 
                 sample_rate: int = 16000,
                 channels: int = 1,
                 chunk_size: int = 4000,
                 format: str = "int16",
                 callback: Optional[Callable[[bytes], None]] = None):
        """
        初始化音频捕获
        
        Args:
            sample_rate: 采样率
            channels: 声道数
            chunk_size: 每次读取的帧数
            format: 音频格式
            callback: 音频数据回调函数
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.format = format
        self.callback = callback
        
        self.stream: Optional[sd.InputStream] = None
        self.is_capturing = False
        self.audio_queue = queue.Queue()
        self.actual_channels = channels
        self.actual_sample_rate = sample_rate
        
        # 查找WASAPI Loopback设备
        self.loopback_device_index = self._find_loopback_device()
        
        if self.loopback_device_index is None:
            error_msg = (
                "未找到WASAPI Loopback设备！\n\n"
                "要捕获桌面音频输出，需要启用Windows的'立体声混音'功能。\n\n"
                "启用步骤：\n"
                "1. 右键点击系统托盘的声音图标\n"
                "2. 选择'声音设置'\n"
                "3. 点击'声音控制面板'\n"
                "4. 切换到'录制'选项卡\n"
                "5. 右键点击空白处，选择'显示禁用的设备'\n"
                "6. 找到'立体声混音'并启用\n\n"
                "这是Windows内置功能，无需安装第三方驱动。"
            )
            raise RuntimeError(error_msg)
    
    def _find_loopback_device(self) -> Optional[int]:
        """查找WASAPI Loopback设备索引"""
        devices = sd.query_devices()
        
        # 查找WASAPI hostapi
        wasapi_hostapi = None
        for i, hostapi in enumerate(sd.query_hostapis()):
            if 'WASAPI' in hostapi.get('name', ''):
                wasapi_hostapi = i
                break
        
        if wasapi_hostapi is None:
            print("错误: 未找到WASAPI hostapi")
            return None
        
        # 获取默认输出设备（我们要捕获它的音频）
        try:
            default_output = sd.query_devices(kind='output')
            default_output_index = default_output.get('index', None)
            default_output_name = default_output.get('name', '')
            
            print(f"默认输出设备: [{default_output_index}] {default_output_name}")
            
            # 在WASAPI中，Loopback设备是特殊的输入设备
            # 查找所有WASAPI输入设备，找到与输出设备对应的Loopback设备
            print("搜索WASAPI Loopback设备...")
            
            # 先列出所有可用的输入设备
            available_inputs = []
            for i, device in enumerate(devices):
                device_hostapi = device.get('hostapi', -1)
                max_input = device.get('max_input_channels', 0)
                
                if device_hostapi == wasapi_hostapi and max_input > 0:
                    device_name = device.get('name', '')
                    available_inputs.append((i, device_name, max_input))
            
            if available_inputs:
                print("\n可用的WASAPI输入设备:")
                for idx, name, channels in available_inputs:
                    print(f"  [{idx}] {name} ({channels}声道)")
            
            # 查找Loopback设备
            for i, device in enumerate(devices):
                device_hostapi = device.get('hostapi', -1)
                max_input = device.get('max_input_channels', 0)
                max_output = device.get('max_output_channels', 0)
                
                # 检查是否是WASAPI设备
                if device_hostapi == wasapi_hostapi:
                    device_name = device.get('name', '')
                    name_lower = device_name.lower()
                    
                    # Loopback设备通常是既有输出又有输入通道的设备
                    # 或者名称包含输出设备名称、"stereo mix"、"立体声混音"等
                    if max_input > 0:
                        # 检查是否是Loopback设备
                        is_loopback = (
                            'loopback' in name_lower or
                            'stereo mix' in name_lower or
                            '立体声混音' in device_name or
                            'stereo' in name_lower and 'mix' in name_lower or
                            default_output_name.lower() in name_lower or
                            device_name == default_output_name or
                            (max_output > 0 and max_input > 0)  # 既有输入又有输出
                        )
                        
                        if is_loopback:
                            # 验证设备是否真的支持输入
                            try:
                                # 尝试检查设备配置（先试2声道）
                                sd.check_input_settings(device=i, channels=2, samplerate=44100)
                                print(f"\n找到Loopback设备: [{i}] {device_name} (2声道)")
                                return i
                            except:
                                try:
                                    # 如果2声道失败，试1声道
                                    sd.check_input_settings(device=i, channels=1, samplerate=44100)
                                    print(f"\n找到Loopback设备: [{i}] {device_name} (1声道)")
                                    return i
                                except:
                                    continue
            
            # 如果找不到Loopback设备，提供详细的启用说明
            print("\n" + "="*60)
            print("未找到Loopback设备！")
            print("="*60)
            print("\n要捕获桌面音频输出，需要启用Windows的'立体声混音'功能：")
            print("\n启用步骤：")
            print("1. 右键点击系统托盘的声音图标")
            print("2. 选择'声音设置'或'打开声音设置'")
            print("3. 点击'声音控制面板'（在右侧相关设置中）")
            print("4. 切换到'录制'选项卡")
            print("5. 右键点击空白处，选择'显示禁用的设备'")
            print("6. 找到'立体声混音'（Stereo Mix）")
            print("7. 右键点击'立体声混音'，选择'启用'")
            print("8. 右键点击'立体声混音'，选择'设置为默认设备'（可选）")
            print("9. 重新运行程序")
            print("\n如果仍然找不到'立体声混音'，可能是：")
            print("- 声卡驱动不支持此功能")
            print("- 需要在声卡驱动程序中启用（如Realtek音频管理器）")
            print("="*60 + "\n")
            
            return None
            
        except Exception as e:
            print(f"查找Loopback设备时出错: {e}")
            return None
    
    def _audio_callback(self, indata, frames, time_info, status):
        """sounddevice回调函数"""
        if status:
            print(f"音频捕获状态: {status}")
        
        # indata是numpy数组，shape为 (frames, channels)
        # 转换为单声道（如果需要）
        audio_data = indata
        if self.actual_channels > 1 and self.channels == 1:
            # 转换为单声道
            if len(indata.shape) == 2:
                audio_data = np.mean(indata, axis=1, keepdims=True)
        
        # 转换为字节
        if self.format == "int16":
            audio_bytes = (audio_data * 32767).astype(np.int16).tobytes()
        elif self.format == "int32":
            audio_bytes = (audio_data * 2147483647).astype(np.int32).tobytes()
        elif self.format == "float32":
            audio_bytes = audio_data.astype(np.float32).tobytes()
        else:
            audio_bytes = (audio_data * 32767).astype(np.int16).tobytes()
        
        if self.callback:
            self.callback(audio_bytes)
        else:
            self.audio_queue.put(audio_bytes)
    
    def start(self) -> None:
        """开始音频捕获"""
        if self.is_capturing:
            return
        
        try:
            # 获取设备信息
            device_info = sd.query_devices(self.loopback_device_index)
            max_input_channels = device_info.get('max_input_channels', 0)
            default_sample_rate = device_info.get('default_samplerate', self.sample_rate)
            
            # 确定实际使用的声道数
            actual_channels = self.channels
            if max_input_channels > 0:
                if self.channels > max_input_channels:
                    actual_channels = max_input_channels
                    print(f"提示: 设备使用{actual_channels}声道（配置为{self.channels}声道）")
            else:
                # 如果max_input_channels为0，尝试使用2声道（Loopback通常是立体声）
                actual_channels = 2
                print(f"提示: Loopback设备使用{actual_channels}声道，将自动转换为单声道")
            
            # 确定实际使用的采样率
            actual_sample_rate = int(default_sample_rate)
            if actual_sample_rate != self.sample_rate:
                print(f"提示: 设备使用{actual_sample_rate}Hz采样率（配置为{self.sample_rate}Hz）")
            
            # 检查设备是否支持该配置
            try:
                sd.check_input_settings(
                    device=self.loopback_device_index,
                    channels=actual_channels,
                    samplerate=actual_sample_rate
                )
            except Exception as e:
                print(f"设备不支持配置 {actual_channels}声道, {actual_sample_rate}Hz: {e}")
                # 尝试其他配置
                if actual_channels == 2:
                    # 如果2声道失败，尝试1声道
                    actual_channels = 1
                    print(f"尝试使用1声道")
                    try:
                        sd.check_input_settings(
                            device=self.loopback_device_index,
                            channels=actual_channels,
                            samplerate=actual_sample_rate
                        )
                    except:
                        # 如果还是失败，尝试使用设备默认采样率
                        actual_sample_rate = int(device_info.get('default_samplerate', 44100))
                        print(f"尝试使用设备默认采样率: {actual_sample_rate}Hz")
            
            # 打开音频流
            # 在WASAPI中，Loopback设备已经是输入设备，可以直接使用
            self.stream = sd.InputStream(
                device=self.loopback_device_index,
                channels=actual_channels,
                samplerate=actual_sample_rate,
                blocksize=self.chunk_size,
                callback=self._audio_callback,
                dtype='float32'  # sounddevice使用float32内部处理
            )
            
            self.actual_channels = actual_channels
            self.actual_sample_rate = actual_sample_rate
            
            self.stream.start()
            self.is_capturing = True
            print(f"音频捕获已启动 (设备索引: {self.loopback_device_index}, {actual_channels}声道, {actual_sample_rate}Hz)")
            
        except Exception as e:
            print(f"启动音频捕获失败: {e}")
            raise
    
    def stop(self) -> None:
        """停止音频捕获"""
        if not self.is_capturing:
            return
        
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
        
        self.is_capturing = False
        print("音频捕获已停止")
    
    def read(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        读取音频数据
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            音频数据，如果超时则返回None
        """
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_available_devices(self) -> list:
        """获取所有可用的音频设备"""
        devices = []
        try:
            all_devices = sd.query_devices()
            for i, device in enumerate(all_devices):
                devices.append({
                    'index': i,
                    'name': device.get('name', 'Unknown'),
                    'maxInputChannels': device.get('max_input_channels', 0),
                    'maxOutputChannels': device.get('max_output_channels', 0),
                    'defaultSampleRate': device.get('default_samplerate', 44100)
                })
        except:
            pass
        return devices
    
    def close(self) -> None:
        """关闭音频捕获并释放资源"""
        self.stop()

