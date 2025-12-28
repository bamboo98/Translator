"""
使用CABLE虚拟声卡的音频捕获模块
参考音频流处理方式：分块累积处理
"""
import pyaudio
import threading
import queue
from typing import Optional, Callable

class AudioCapture:
    """音频捕获类，使用CABLE虚拟声卡捕获系统音频"""
    
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
            format: 音频格式
            callback: 音频数据回调函数（接收累积的音频块）
            volume_callback: 音量回调函数（接收音量值0-100）
            device_index: 设备索引，如果为None则自动查找CABLE设备
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
        
        self.audio = pyaudio.PyAudio()
        self.stream: Optional[pyaudio.Stream] = None
        self.is_capturing = False
        self.audio_queue = queue.Queue()
        
        # 实际使用的采样率（可能与目标采样率不同）
        self.actual_sample_rate = sample_rate
        
        # chunk_size 和 process_interval 将在 start() 中根据实际采样率动态计算
        self.chunk_size = None
        self.process_interval = None
        
        # 分块累积处理相关
        self.frames = []  # 累积的音频帧
        self.frame_count = 0
        
        # 断句相关
        self.is_speaking = False  # 是否正在说话
        self.silence_start_time = None  # 静音开始时间（时间戳）
        import time
        self.time = time  # 保存time模块引用
        
        # 查找CABLE设备
        if device_index is None:
            self.device_index = self._find_cable_device()
        else:
            self.device_index = device_index
        
        if self.device_index is None:
            raise RuntimeError(
                "未找到CABLE虚拟声卡设备！\n\n"
                "请确保已安装VB-Audio Cable，并在系统声音设置中：\n"
                "1. 将播放设备设置为CABLE Input\n"
                "2. 在录制设备中可以看到CABLE Output\n"
                "3. 在CABLE Output属性中关闭'允许应用程序独占控制此设备'"
            )
    
    def _find_cable_device(self) -> Optional[int]:
        """查找CABLE虚拟声卡设备"""
        print("搜索CABLE虚拟声卡设备...")
        cable_devices = []
        
        for i in range(self.audio.get_device_count()):
            try:
                device_info = self.audio.get_device_info_by_index(i)
                device_name = device_info.get('name', '')
                max_input_channels = device_info.get('maxInputChannels', 0)
                
                # 查找包含"CABLE Output"的设备
                if 'CABLE Output' in device_name and max_input_channels > 0:
                    cable_devices.append((i, device_name, max_input_channels))
                    print(f"找到CABLE设备: [{i}] {device_name} ({max_input_channels}声道)")
            except Exception as e:
                continue
        
        if cable_devices:
            # 优先选择第一个找到的CABLE设备
            device_index, device_name, channels = cable_devices[0]
            print(f"使用CABLE设备: [{device_index}] {device_name}")
            return device_index
        
        # 如果没找到，列出所有输入设备供参考
        print("\n可用的输入设备:")
        for i in range(self.audio.get_device_count()):
            try:
                device_info = self.audio.get_device_info_by_index(i)
                if device_info.get('maxInputChannels', 0) > 0:
                    print(f"  [{i}] {device_info.get('name', 'Unknown')}")
            except:
                continue
        
        return None
    
    def get_available_devices(self) -> list:
        """获取所有可用的音频输入设备"""
        devices = []
        for i in range(self.audio.get_device_count()):
            try:
                device_info = self.audio.get_device_info_by_index(i)
                if device_info.get('maxInputChannels', 0) > 0:
                    devices.append({
                        'index': i,
                        'name': device_info.get('name', 'Unknown'),
                        'maxInputChannels': device_info.get('maxInputChannels', 0),
                        'defaultSampleRate': device_info.get('defaultSampleRate', 44100),
                        'isCABLE': 'CABLE Output' in device_info.get('name', '')
                    })
            except:
                continue
        return devices
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio回调函数 - 分块累积处理"""
        if status:
            print(f"音频捕获状态: {status}")
        
        
        # 处理音频数据：如果是多声道但需要单声道，先转换
        audio_data = in_data
        mono_data_for_volume = in_data  # 用于音量计算的单声道数据
        
        # 确定实际声道数（如果还没有设置，尝试从数据推断）
        actual_channels = getattr(self, 'actual_channels', None)
        if actual_channels is None:
            # 如果还没有设置actual_channels，尝试推断
            # 假设如果设备支持多声道，可能是2声道
            if hasattr(self, 'device_index') and self.device_index is not None:
                try:
                    device_info = self.audio.get_device_info_by_index(self.device_index)
                    max_input_channels = device_info.get('maxInputChannels', 0)
                    actual_channels = 2 if max_input_channels >= 2 else 1
                except:
                    actual_channels = 1
            else:
                actual_channels = 1
        
        # 转换为单声道（如果实际是多声道）
        if actual_channels > 1 and self.channels == 1:
            try:
                from src.audio.processor import AudioProcessor
                # 转换为numpy数组
                audio_array = AudioProcessor.bytes_to_numpy(in_data, self.format)
                # 转换为单声道
                mono_array = AudioProcessor.convert_to_mono(audio_array, actual_channels)
                # 转换回字节
                audio_data = AudioProcessor.numpy_to_bytes(mono_array, self.format)
                mono_data_for_volume = audio_data  # 使用转换后的单声道数据
            except Exception as e:
                print(f"声道转换失败: {e}，使用原始音频")
                # 如果转换失败，尝试直接计算（假设是单声道）
                audio_data = in_data
                mono_data_for_volume = in_data
        
        # 计算当前音频块的音量（使用处理后的单声道数据）
        if self.volume_callback:
            try:
                from src.audio.processor import AudioProcessor
                volume = AudioProcessor.calculate_volume(mono_data_for_volume, self.format, channels=1)
                self.volume_callback(volume)
            except Exception as e:
                print(f"音量计算错误: {e}")
                import traceback
                traceback.print_exc()
        
        # 累积音频帧和音量
        self.frames.append(audio_data)
        self.frame_count += 1
        
        # 计算当前帧的音量并累积
        if not hasattr(self, 'frame_volumes'):
            self.frame_volumes = []
        try:
            from src.audio.processor import AudioProcessor
            frame_volume = AudioProcessor.calculate_volume(mono_data_for_volume, self.format, channels=1)
            self.frame_volumes.append(frame_volume)
        except:
            frame_volume = 0.0
            self.frame_volumes.append(0.0)
        
        # 断句逻辑：根据音量阈值判断是否在说话
        current_time = self.time.time()
        if frame_volume > self.volume_threshold:
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
                            from src.audio.processor import AudioProcessor
                            # 转换为numpy数组
                            audio_array = AudioProcessor.bytes_to_numpy(audio_bytes, self.format)
                            # 重采样到目标采样率
                            resampled_array = AudioProcessor.resample(
                                audio_array, 
                                self.actual_sample_rate, 
                                self.sample_rate
                            )
                            # 转换回字节
                            audio_bytes = AudioProcessor.numpy_to_bytes(resampled_array, self.format)
                        except Exception as e:
                            print(f"重采样失败: {e}，使用原始音频")
                    
                    # 调用回调函数处理累积的音频块
                    if self.callback:
                        try:
                            self.callback(audio_bytes)
                        except Exception as e:
                            print(f"音频回调处理错误: {e}")
                    else:
                        self.audio_queue.put(audio_bytes)
                    
                    return (None, pyaudio.paContinue)
        
        # 每3秒处理一次（根据参考代码：16000 * 3 // 1024）
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
                return (None, pyaudio.paContinue)
            
            # 如果实际采样率与目标采样率不同，进行重采样
            if self.actual_sample_rate != self.sample_rate:
                try:
                    from src.audio.processor import AudioProcessor
                    # 转换为numpy数组
                    audio_array = AudioProcessor.bytes_to_numpy(audio_bytes, self.format)
                    # 重采样到目标采样率
                    resampled_array = AudioProcessor.resample(
                        audio_array, 
                        self.actual_sample_rate, 
                        self.sample_rate
                    )
                    # 转换回字节
                    audio_bytes = AudioProcessor.numpy_to_bytes(resampled_array, self.format)
                except Exception as e:
                    print(f"重采样失败: {e}，使用原始音频")
            
            # 调用回调函数处理累积的音频块
            if self.callback:
                try:
                    self.callback(audio_bytes)
                except Exception as e:
                    print(f"音频回调处理错误: {e}")
            else:
                self.audio_queue.put(audio_bytes)
        
        return (None, pyaudio.paContinue)
    
    def start(self) -> None:
        """开始音频捕获"""
        if self.is_capturing:
            return
        
        if self.device_index is None:
            raise RuntimeError(
                "未选择音频设备！\n\n"
                "请确保已安装VB-Audio Cable，并在系统声音设置中：\n"
                "1. 将播放设备设置为CABLE Input\n"
                "2. 在录制设备中可以看到CABLE Output\n"
                "3. 在CABLE Output属性中关闭'允许应用程序独占控制此设备'\n"
                "4. 在程序中选择CABLE Output作为输入设备"
            )
        
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
            
            # 获取设备信息
            device_info = self.audio.get_device_info_by_index(self.device_index)
            device_name = device_info.get('name', 'Unknown')
            max_input_channels = device_info.get('maxInputChannels', 0)
            default_sample_rate = int(device_info.get('defaultSampleRate', 44100))
            
            # 打印设备信息用于调试
            print(f"设备信息: {device_name}")
            print(f"  - 最大输入声道数: {max_input_channels}")
            print(f"  - PyAudio报告的默认采样率: {default_sample_rate}Hz")
            print(f"  - 注意: 系统设置中CABLE Output可能是2通道, 24位, 48000Hz")
            
            # 确定使用的声道数
            # CABLE Output通常是立体声（2声道），优先使用2声道
            if max_input_channels >= 2:
                # 设备支持多声道，强制使用2声道捕获（CABLE通常是立体声）
                actual_channels = 2
                print(f"提示: CABLE设备使用2声道捕获（系统默认），将自动转换为单声道供Vosk使用")
            elif max_input_channels == 1:
                actual_channels = 1
                print(f"警告: 设备只支持单声道，可能不是正确的CABLE设备")
            else:
                # 如果maxInputChannels为0，尝试使用2声道（某些设备可能报告不正确）
                actual_channels = 2
                print(f"警告: 设备报告maxInputChannels=0，尝试使用2声道")
            
            # 保存实际声道数，用于后续处理
            self.actual_channels = actual_channels
            
            # 尝试不同的采样率配置
            # 优先顺序：48000Hz（CABLE常见默认值） -> 设备报告的默认采样率 -> 目标采样率 -> 其他常见采样率
            try_sample_rates = []
            # 优先尝试48000Hz（CABLE的常见默认值，即使PyAudio报告的是其他值）
            if 48000 not in try_sample_rates:
                try_sample_rates.append(48000)
            # 然后尝试PyAudio报告的默认采样率
            if default_sample_rate not in try_sample_rates:
                try_sample_rates.append(default_sample_rate)
            # 添加目标采样率
            if self.sample_rate not in try_sample_rates:
                try_sample_rates.append(self.sample_rate)
            # 添加其他常见采样率作为备选
            common_rates = [44100, 22050, 24000, 32000]
            for rate in common_rates:
                if rate not in try_sample_rates:
                    try_sample_rates.append(rate)
            
            stream_opened = False
            last_error = None
            
            for try_rate in try_sample_rates:
                try:
                    print(f"尝试采样率: {try_rate}Hz")
                    
                    # 保存实际使用的采样率
                    self.actual_sample_rate = try_rate
                    
                    # 根据实际采样率动态计算chunk_size（每次读取约0.1秒的数据）
                    # 这样可以保证回调频率适中，不会太频繁也不会太慢
                    self.chunk_size = int(self.actual_sample_rate * 0.1)
                    # 确保chunk_size在合理范围内（最小1024，最大8192）
                    self.chunk_size = max(1024, min(8192, self.chunk_size))
                    
                    # 根据处理间隔秒数和采样率计算需要累积多少帧
                    # 例如：48000Hz * 3秒 = 144000帧，需要累积这么多帧后处理一次
                    total_frames_for_interval = int(self.actual_sample_rate * self.process_interval_seconds)
                    self.process_interval = total_frames_for_interval // self.chunk_size
                    # 确保至少累积1帧
                    if self.process_interval < 1:
                        self.process_interval = 1
                    
                    # 打开音频流，使用计算出的chunk_size
                    self.stream = self.audio.open(
                        format=pyaudio_format,
                        channels=actual_channels,
                        rate=try_rate,
                        input=True,
                        input_device_index=self.device_index,
                        frames_per_buffer=self.chunk_size,
                        stream_callback=self._audio_callback,
                        start=False
                    )
                    
                    stream_opened = True
                    print(f"采样率配置成功: {try_rate}Hz")
                    print(f"处理间隔配置: {self.process_interval_seconds}秒")
                    print(f"Chunk大小: {self.chunk_size} 帧（约{self.chunk_size/self.actual_sample_rate:.3f}秒）")
                    print(f"处理间隔: 每{self.process_interval}个chunk（约{self.process_interval * self.chunk_size / self.actual_sample_rate:.2f}秒）处理一次")
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
            
            if not stream_opened:
                raise RuntimeError(f"无法打开音频流，尝试的采样率都失败。最后错误: {last_error}")
            
            # 如果实际采样率与目标采样率不同，提示需要重采样
            if self.actual_sample_rate != self.sample_rate:
                print(f"提示: 设备使用{self.actual_sample_rate}Hz采样率（目标{self.sample_rate}Hz），将自动重采样")
            
            # 重置累积帧和音量
            self.frames = []
            self.frame_count = 0
            self.frame_volumes = []
            # 重置断句相关状态
            self.is_speaking = False
            self.silence_start_time = None
            
            # 启动流
            self.stream.start_stream()
            self.is_capturing = True
            print(f"音频捕获已启动: [{self.device_index}] {device_name}")
            print(f"  - 捕获配置: {actual_channels}声道, {self.actual_sample_rate}Hz, {self.format}")
            print(f"  - 目标配置: {self.channels}声道, {self.sample_rate}Hz (用于Vosk)")
            if self.actual_sample_rate != self.sample_rate or actual_channels != self.channels:
                print(f"  - 将自动进行格式转换（重采样/声道转换）")
            
        except Exception as e:
            print(f"启动音频捕获失败: {e}")
            raise
    
    def stop(self) -> None:
        """停止音频捕获"""
        if not self.is_capturing:
            return
        
        self.is_capturing = False
        
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                print(f"停止音频流时出错: {e}")
        
        # 清空累积的帧和音量
        self.frames = []
        self.frame_count = 0
        if hasattr(self, 'frame_volumes'):
            self.frame_volumes = []
        # 重置断句相关状态
        self.is_speaking = False
        self.silence_start_time = None
        
        print("音频捕获已停止")
    
    def read(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        读取累积的音频数据块
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            音频数据块，如果超时则返回None
        """
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def close(self) -> None:
        """关闭音频捕获并释放资源"""
        self.stop()
        if self.audio:
            try:
                self.audio.terminate()
            except:
                pass

