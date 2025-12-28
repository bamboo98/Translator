"""
使用pyaudiowpatch的桌面音频捕获模块
参考test_audio.py中的实现
"""
import pyaudiowpatch
import numpy as np
from typing import Optional, Callable

class LoopbackAudioCapture:
    """桌面音频捕获类，使用pyaudiowpatch捕获系统音频"""
    
    def __init__(self, 
                 sample_rate: int = 16000,
                 channels: int = 1,
                 process_interval_seconds: float = 3.0,
                 format: str = "int16",
                 callback: Optional[Callable[[bytes], None]] = None,
                 volume_callback: Optional[Callable[[float], None]] = None,
                 device_index: Optional[int] = None,
                 volume_threshold: float = 1.0,
                 sentence_break_interval: float = 2.0):
        """
        初始化音频捕获
        
        Args:
            sample_rate: 目标采样率（用于Vosk）
            channels: 声道数
            process_interval_seconds: 处理间隔（秒），默认3秒
            format: 音频格式（仅支持float32，内部会转换为int16）
            callback: 音频数据回调函数（接收累积的音频块）
            volume_callback: 音量回调函数（接收音量值0-100）
            device_index: 设备索引，如果为None则使用默认WASAPI环回设备
            volume_threshold: 音量阈值（0-100），低于此值不传递给识别模型
            sentence_break_interval: 断句间隔（秒），静音超过此时间后立即发送数据
        """
        self.sample_rate = sample_rate  # 目标采样率（用于Vosk）
        self.channels = channels
        self.process_interval_seconds = process_interval_seconds
        self.format = format
        self.callback = callback
        self.volume_callback = volume_callback
        self.volume_threshold = volume_threshold
        self.sentence_break_interval = sentence_break_interval
        
        self.pa = None
        self.audio_stream = None
        self.is_capturing = False
        
        # 实际使用的采样率（可能与目标采样率不同）
        self.actual_sample_rate = sample_rate
        
        # chunk_size 和 process_interval 将在 start() 中根据实际采样率动态计算
        self.chunk_size = None
        self.process_interval = None
        
        # 分块累积处理相关
        self.frames = []  # 累积的音频帧
        self.frame_count = 0
        self.frame_volumes = []  # 累积的音量值
        
        # 断句相关
        self.is_speaking = False  # 是否正在说话
        self.silence_start_time = None  # 静音开始时间（时间戳）
        import time
        self.time = time  # 保存time模块引用
        
        # 查找设备
        if device_index is None:
            self.device_index = None  # 将在start()中使用默认WASAPI环回设备
        else:
            self.device_index = device_index
    
    def get_available_devices(self) -> list:
        """获取所有可用的环回设备"""
        devices = []
        try:
            if self.pa is None:
                self.pa = pyaudiowpatch.PyAudio()
            for device in self.pa.get_loopback_device_info_generator():
                devices.append({
                    'index': device["index"],
                    'name': device["name"],
                    'maxInputChannels': device.get("maxInputChannels", 0),
                    'defaultSampleRate': device.get("defaultSampleRate", 44100),
                    'isCABLE': False  # 环回设备不是CABLE
                })
        except Exception as e:
            print(f"枚举环回设备失败: {e}")
        return devices
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio回调函数 - 分块累积处理"""
        if status:
            print(f"音频捕获状态: {status}")
        
        # 处理音频数据：转换为numpy数组（float32格式）
        samples = np.frombuffer(in_data, dtype=np.float32)
        
        # 计算当前音频块的音量（用于显示和过滤）
        rms = np.sqrt(np.mean(samples ** 2))
        peak = np.max(np.abs(samples))
        # 转换为0-100的百分比（线性）
        rms_percent = min(100, rms * 100)
        peak_percent = min(100, peak * 100)
        linear_volume = rms_percent * 0.7 + peak_percent * 0.3
        
        # 使用对数曲线映射，提高低音量时的灵敏度
        # 使用 log(1 + v * scale) / log(1 + 100 * scale) * 100
        # scale 控制曲线陡峭程度，值越大低音量越敏感
        scale = 0.15  # 可调整参数，范围0.1-0.3，值越大低音量越敏感
        if linear_volume > 0:
            # 对数映射：低音量时增长快，高音量时增长慢
            log_volume = np.log1p(linear_volume * scale) / np.log1p(100 * scale) * 100
            volume = min(100, log_volume)
        else:
            volume = 0.0
        
        # 发送实时音量更新信号（用于UI显示）
        if self.volume_callback:
            self.volume_callback(volume)
        
        # 转换为 int16 格式（用于累积和识别）
        # float32 范围是 -1.0 到 1.0，需要缩放到 int16 范围
        samples_int16 = (samples * 32767).astype(np.int16)
        audio_data = samples_int16.tobytes()
        
        # 累积音频帧和音量
        self.frames.append(audio_data)
        self.frame_count += 1
        self.frame_volumes.append(volume)
        
        # 断句逻辑：根据音量阈值判断是否在说话
        current_time = self.time.time()
        if volume > self.volume_threshold:
            # 音量大于阈值，正在说话
            self.is_speaking = True
            self.silence_start_time = None  # 清空静音统计时长
        else:
            # 音量小于阈值，累计静音统计时长
            if self.silence_start_time is None:
                self.silence_start_time = current_time
            silence_duration = current_time - self.silence_start_time
            
            # 如果静音时长大于断句间隔，并且正在说话，立即发送数据
            if silence_duration >= self.sentence_break_interval and self.is_speaking:
                self.is_speaking = False
                # 立即发送累积的数据（无视process_interval条件）
                if self.frames:
                    audio_bytes = b''.join(self.frames)
                    
                    # 计算累积块的平均音量
                    avg_volume = 0.0
                    if self.frame_volumes:
                        avg_volume = sum(self.frame_volumes) / len(self.frame_volumes)
                    
                    # 清空累积的帧和音量
                    self.frames = []
                    self.frame_count = 0
                    self.frame_volumes = []
                    
                    # 如果实际采样率与目标采样率不同，进行重采样
                    if self.actual_sample_rate != self.sample_rate:
                        try:
                            # 转换为numpy数组
                            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                            # 重采样到目标采样率
                            ratio = self.sample_rate / self.actual_sample_rate
                            original_length = len(audio_array)
                            target_length = int(original_length * ratio)
                            indices = np.linspace(0, original_length - 1, target_length)
                            resampled_array = np.interp(indices, np.arange(original_length), audio_array)
                            # 转换回int16并转为字节
                            audio_bytes = resampled_array.astype(np.int16).tobytes()
                        except Exception as e:
                            print(f"重采样失败: {e}，使用原始音频")
                    
                    # 调用回调函数处理累积的音频块
                    if self.callback:
                        try:
                            self.callback(audio_bytes)
                        except Exception as e:
                            print(f"音频回调处理错误: {e}")
                    
                    return (None, pyaudiowpatch.paContinue)
        
        # 达到处理间隔时处理累积的音频块
        if len(self.frames) >= self.process_interval:
            # 合并所有累积的帧
            audio_bytes = b''.join(self.frames)
            
            # 计算累积块的平均音量
            avg_volume = 0.0
            if self.frame_volumes:
                avg_volume = sum(self.frame_volumes) / len(self.frame_volumes)
            
            # 清空累积的帧和音量
            self.frames = []
            self.frame_count = 0
            self.frame_volumes = []
            
            # 如果平均音量 <= 阈值，不传递给识别模型
            if avg_volume <= self.volume_threshold:
                return (None, pyaudiowpatch.paContinue)
            
            # 如果实际采样率与目标采样率不同，进行重采样
            if self.actual_sample_rate != self.sample_rate:
                try:
                    # 转换为numpy数组
                    audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                    # 重采样到目标采样率
                    ratio = self.sample_rate / self.actual_sample_rate
                    original_length = len(audio_array)
                    target_length = int(original_length * ratio)
                    indices = np.linspace(0, original_length - 1, target_length)
                    resampled_array = np.interp(indices, np.arange(original_length), audio_array)
                    # 转换回int16并转为字节
                    audio_bytes = resampled_array.astype(np.int16).tobytes()
                except Exception as e:
                    print(f"重采样失败: {e}，使用原始音频")
            
            # 调用回调函数处理累积的音频块
            if self.callback:
                try:
                    self.callback(audio_bytes)
                except Exception as e:
                    print(f"音频回调处理错误: {e}")
        
        return (None, pyaudiowpatch.paContinue)
    
    def start(self) -> None:
        """开始音频捕获"""
        if self.is_capturing:
            return
        
        try:
            if self.pa is None:
                self.pa = pyaudiowpatch.PyAudio()
            
            # 获取设备信息
            if self.device_index is None:
                device_info = self.pa.get_default_wasapi_loopback()
            else:
                device_info = self.pa.get_device_info_by_index(self.device_index)
            
            device_name = device_info["name"]
            original_sample_rate = int(device_info["defaultSampleRate"])
            self.actual_sample_rate = original_sample_rate
            
            # 根据采样率自动计算chunk_size（每次读取约0.1秒的数据）
            self.chunk_size = int(original_sample_rate * 0.1)
            # 确保chunk_size在合理范围内（最小1024，最大8192）
            self.chunk_size = max(1024, min(8192, self.chunk_size))
            
            # 根据处理间隔秒数和采样率计算需要累积多少帧
            total_frames_for_interval = int(self.actual_sample_rate * self.process_interval_seconds)
            self.process_interval = total_frames_for_interval // self.chunk_size
            # 确保至少累积1帧
            if self.process_interval < 1:
                self.process_interval = 1
            
            print(f"使用设备: {device_name}")
            print(f"原始采样率: {original_sample_rate}Hz")
            print(f"目标采样率: {self.sample_rate}Hz")
            print(f"处理间隔配置: {self.process_interval_seconds}秒")
            print(f"Chunk大小: {self.chunk_size} 帧（约{self.chunk_size/original_sample_rate:.3f}秒）")
            print(f"处理间隔: 每{self.process_interval}个chunk（约{self.process_interval * self.chunk_size / original_sample_rate:.2f}秒）处理一次")
            
            # 打开音频流（使用原始采样率和回调函数）
            self.audio_stream = self.pa.open(
                rate=original_sample_rate,
                channels=1,
                format=pyaudiowpatch.paFloat32,
                input=True,
                input_device_index=device_info["index"],
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback,
                start=False
            )
            
            # 重置累积帧和音量
            self.frames = []
            self.frame_count = 0
            self.frame_volumes = []
            # 重置断句相关状态
            self.is_speaking = False
            self.silence_start_time = None
            
            # 启动流
            self.audio_stream.start_stream()
            self.is_capturing = True
            
            print(f"音频捕获已启动: {device_name}")
            print(f"  - 捕获配置: 1声道, {self.actual_sample_rate}Hz, float32")
            print(f"  - 目标配置: {self.channels}声道, {self.sample_rate}Hz, int16 (用于Vosk)")
            if self.actual_sample_rate != self.sample_rate:
                print(f"  - 将自动进行重采样")
            
        except Exception as e:
            print(f"启动音频捕获失败: {e}")
            raise
    
    def stop(self) -> None:
        """停止音频捕获"""
        if not self.is_capturing:
            return
        
        self.is_capturing = False
        
        if self.audio_stream:
            try:
                if not self.audio_stream.is_stopped():
                    self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
            except Exception as e:
                print(f"停止音频流时出错: {e}")
        
        # 清空累积的帧和音量
        self.frames = []
        self.frame_count = 0
        self.frame_volumes = []
        # 重置断句相关状态
        self.is_speaking = False
        self.silence_start_time = None
        
        print("音频捕获已停止")
    
    def close(self) -> None:
        """关闭音频捕获并释放资源"""
        self.stop()
        if self.pa:
            try:
                self.pa.terminate()
                self.pa = None
            except Exception as e:
                print(f"终止PyAudio错误: {e}")

