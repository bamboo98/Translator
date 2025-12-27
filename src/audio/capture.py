"""
Windows WASAPI Loopback音频捕获模块
"""
import pyaudio
import threading
import queue
from typing import Optional, Callable
import numpy as np

class AudioCapture:
    """音频捕获类，使用WASAPI Loopback捕获系统音频"""
    
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
        
        self.audio = pyaudio.PyAudio()
        self.stream: Optional[pyaudio.Stream] = None
        self.is_capturing = False
        self.audio_queue = queue.Queue()
        self.actual_channels = channels  # 实际使用的声道数（可能因设备而异）
        self.actual_sample_rate = sample_rate  # 实际使用的采样率（可能因设备而异）
        
        # 查找WASAPI Loopback设备
        self.loopback_device_index = self._find_loopback_device()
        
        if self.loopback_device_index is None:
            raise RuntimeError("未找到WASAPI Loopback设备，请确保使用Windows系统")
    
    def _find_loopback_device(self) -> Optional[int]:
        """查找WASAPI Loopback设备索引"""
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            # WASAPI Loopback设备通常名称包含"Loopback"或"Stereo Mix"
            device_name = device_info.get('name', '').lower()
            if 'loopback' in device_name or 'stereo mix' in device_name:
                # 检查是否是输出设备
                if device_info.get('maxOutputChannels', 0) > 0:
                    return i
        
        # 如果找不到，尝试使用默认输出设备
        try:
            default_output = self.audio.get_default_output_device_info()
            print(f"警告: 未找到专用Loopback设备，使用默认输出设备: {default_output['name']}")
            return default_output['index']
        except:
            return None
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio回调函数"""
        if status:
            print(f"音频捕获状态: {status}")
        
        # 如果实际捕获的是多声道，但需要单声道，进行转换
        audio_data = in_data
        if hasattr(self, 'actual_channels') and self.actual_channels > 1 and self.channels == 1:
            # 转换为单声道
            from src.audio.processor import AudioProcessor
            audio_array = AudioProcessor.bytes_to_numpy(in_data, self.format)
            mono_array = AudioProcessor.convert_to_mono(audio_array, self.actual_channels)
            audio_data = AudioProcessor.numpy_to_bytes(mono_array, self.format)
        
        if self.callback:
            self.callback(audio_data)
        else:
            self.audio_queue.put(audio_data)
        
        return (None, pyaudio.paContinue)
    
    def start(self) -> None:
        """开始音频捕获"""
        if self.is_capturing:
            return
        
        try:
            # 配置音频格式
            if self.format == "int16":
                pyaudio_format = pyaudio.paInt16
            elif self.format == "int32":
                pyaudio_format = pyaudio.paInt32
            elif self.format == "float32":
                pyaudio_format = pyaudio.paFloat32
            else:
                pyaudio_format = pyaudio.paInt16
            
            # 检查设备支持的声道数
            device_info = self.audio.get_device_info_by_index(self.loopback_device_index)
            max_input_channels = device_info.get('maxInputChannels', 0)
            max_output_channels = device_info.get('maxOutputChannels', 0)
            device_name = device_info.get('name', '').lower()
            default_sample_rate = int(device_info.get('defaultSampleRate', self.sample_rate))
            
            # 确定实际使用的声道数和采样率
            # 尝试多种配置，找到设备支持的配置
            channel_configs = []
            
            # 如果是Loopback设备或输出设备的loopback
            is_loopback = 'loopback' in device_name or max_output_channels > 0
            
            if is_loopback:
                # Loopback设备：尝试2声道、1声道
                if max_input_channels >= 2:
                    channel_configs.append(2)
                if max_input_channels >= 1:
                    channel_configs.append(1)
                # 如果maxInputChannels为0，尝试常见配置
                if max_input_channels == 0:
                    channel_configs = [2, 1]  # 先试2声道，再试1声道
            else:
                # 普通输入设备
                if max_input_channels >= self.channels:
                    channel_configs.append(self.channels)
                elif max_input_channels > 0:
                    channel_configs.append(max_input_channels)
                else:
                    raise RuntimeError(f"设备不支持音频输入")
            
            # 尝试不同的配置
            stream_opened = False
            last_error = None
            
            for try_channels in channel_configs:
                try:
                    # 尝试使用设备的默认采样率，如果失败再使用配置的采样率
                    try_sample_rates = [default_sample_rate, self.sample_rate]
                    if default_sample_rate != self.sample_rate:
                        try_sample_rates.append(self.sample_rate)
                    
                    for try_rate in try_sample_rates:
                        try:
                            print(f"尝试配置: {try_channels}声道, {try_rate}Hz采样率")
                            self.stream = self.audio.open(
                                format=pyaudio_format,
                                channels=try_channels,
                                rate=try_rate,
                                input=True,
                                input_device_index=self.loopback_device_index,
                                frames_per_buffer=self.chunk_size,
                                stream_callback=self._audio_callback
                            )
                            
                            # 保存实际使用的配置
                            self.actual_channels = try_channels
                            self.actual_sample_rate = try_rate
                            
                            stream_opened = True
                            print(f"音频捕获配置成功: {try_channels}声道, {try_rate}Hz采样率")
                            break
                        except Exception as e:
                            last_error = e
                            if self.stream:
                                try:
                                    self.stream.close()
                                except:
                                    pass
                                self.stream = None
                            continue
                    
                    if stream_opened:
                        break
                        
                except Exception as e:
                    last_error = e
                    continue
            
            if not stream_opened:
                raise RuntimeError(f"无法打开音频流，尝试的配置都失败。最后错误: {last_error}")
            
            # 如果实际使用的声道数与配置不同，提示用户
            if self.actual_channels != self.channels:
                if self.actual_channels == 2 and self.channels == 1:
                    print(f"提示: 设备使用{self.actual_channels}声道，将自动转换为单声道")
                else:
                    print(f"提示: 设备使用{self.actual_channels}声道（配置为{self.channels}声道）")
            
            # 如果实际使用的采样率与配置不同，提示用户
            if hasattr(self, 'actual_sample_rate') and self.actual_sample_rate != self.sample_rate:
                print(f"提示: 设备使用{self.actual_sample_rate}Hz采样率（配置为{self.sample_rate}Hz）")
            
            self.stream.start_stream()
            self.is_capturing = True
            print(f"音频捕获已启动 (设备索引: {self.loopback_device_index})")
            
        except Exception as e:
            print(f"启动音频捕获失败: {e}")
            raise
    
    def stop(self) -> None:
        """停止音频捕获"""
        if not self.is_capturing:
            return
        
        if self.stream:
            try:
                self.stream.stop_stream()
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
        for i in range(self.audio.get_device_count()):
            try:
                device_info = self.audio.get_device_info_by_index(i)
                devices.append({
                    'index': i,
                    'name': device_info.get('name', 'Unknown'),
                    'maxInputChannels': device_info.get('maxInputChannels', 0),
                    'maxOutputChannels': device_info.get('maxOutputChannels', 0),
                    'defaultSampleRate': device_info.get('defaultSampleRate', 44100)
                })
            except:
                continue
        return devices
    
    def close(self) -> None:
        """关闭音频捕获并释放资源"""
        self.stop()
        if self.audio:
            self.audio.terminate()

