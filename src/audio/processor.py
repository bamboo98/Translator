"""
音频预处理模块
"""
import numpy as np
import subprocess
import os
import threading
from pathlib import Path
from typing import Union, Optional

class FFmpegResampler:
    """使用持久化 ffmpeg 进程的重采样器（适合实时流）"""
    
    def __init__(self, original_rate: int, target_rate: int, 
                 format: str = "s16le", channels: int = 1):
        """
        初始化 ffmpeg 重采样器
        
        Args:
            original_rate: 原始采样率
            target_rate: 目标采样率
            format: 音频格式 (s16le, s32le, flt 等)
            channels: 声道数
        """
        self.original_rate = original_rate
        self.target_rate = target_rate
        self.format = format
        self.channels = channels
        self.process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.ffmpeg_path = self._find_ffmpeg()
        self.enabled = self.ffmpeg_path is not None
        
        if not self.enabled:
            print("警告: 未找到 ffmpeg.exe，将使用简单插值重采样")
        else:
            self._start_process()
    
    def _find_ffmpeg(self) -> Optional[str]:
        """查找 ffmpeg.exe 路径"""
        # 首先尝试 tools\ffmpeg.exe（相对路径）
        tools_path = Path(__file__).parent.parent.parent / "tools" / "ffmpeg.exe"
        if tools_path.exists():
            return str(tools_path.absolute())
        
        # 尝试系统 PATH 中的 ffmpeg
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=1
            )
            if result.returncode == 0:
                return 'ffmpeg'
        except:
            pass
        
        return None
    
    def _start_process(self):
        """启动 ffmpeg 进程"""
        if not self.enabled:
            return
        
        try:
            # 构建 ffmpeg 命令
            cmd = [
                self.ffmpeg_path,
                '-f', self.format,  # 输入格式
                '-ar', str(self.original_rate),  # 输入采样率
                '-ac', str(self.channels),  # 输入声道数
                '-i', 'pipe:0',  # 从 stdin 读取
                '-af', 'aresample',  # 使用 aresample 滤镜（高质量重采样）
                '-f', self.format,  # 输出格式
                '-ar', str(self.target_rate),  # 输出采样率
                '-ac', str(self.channels),  # 输出声道数
                'pipe:1',  # 输出到 stdout
                '-loglevel', 'error'  # 只显示错误
            ]
            
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0  # 无缓冲，实时处理
            )
        except Exception as e:
            print(f"启动 ffmpeg 进程失败: {e}")
            self.enabled = False
            self.process = None
    
    def resample(self, audio_data: bytes) -> bytes:
        """
        重采样音频数据
        
        Args:
            audio_data: 原始音频字节数据
            
        Returns:
            重采样后的音频字节数据
        """
        if not self.enabled or self.process is None:
            raise RuntimeError("ffmpeg 重采样器未启用或进程未启动")
        
        with self.lock:
            # 检查进程是否还在运行
            if self.process.poll() is not None:
                # 进程已结束，尝试重启
                try:
                    self._start_process()
                    if self.process is None or self.process.poll() is not None:
                        raise RuntimeError("无法重启 ffmpeg 进程")
                except Exception as e:
                    print(f"重启 ffmpeg 进程失败: {e}")
                    self.enabled = False
                    raise RuntimeError(f"ffmpeg 进程异常: {e}")
            
            try:
                # 写入输入数据
                print(f'写入输入数据: {len(audio_data)} 字节')
                self.process.stdin.write(audio_data)
                self.process.stdin.flush()
                print(f'写入输入数据完成')
                
                # 计算期望的输出大小
                # 根据格式确定每样本字节数
                if self.format == "s16le":
                    bytes_per_sample = 2
                elif self.format == "s32le":
                    bytes_per_sample = 4
                elif self.format == "flt":
                    bytes_per_sample = 4
                else:
                    bytes_per_sample = 2  # 默认
                
                input_samples = len(audio_data) // bytes_per_sample
                output_samples = int(input_samples * self.target_rate / self.original_rate)
                output_size = output_samples * bytes_per_sample
                
                # 读取输出数据
                output_data = b''
                remaining = output_size
                max_reads = 100  # 防止无限循环
                read_count = 0
                
                # 分块读取，避免阻塞
                while remaining > 0 and read_count < max_reads:
                    print(f'准备读取{remaining} 字节')
                    chunk = self.process.stdout.read(min(remaining, 8192))
                    print(f'读取输出数据: {len(chunk)} 字节')
                    if not chunk:
                        # 如果没有数据，等待一小段时间
                        import time
                        time.sleep(0.001)  # 1ms
                        read_count += 1
                        if read_count >= max_reads:
                            break
                        continue
                    output_data += chunk
                    remaining -= len(chunk)
                    read_count = 0  # 重置计数
                
                if len(output_data) < output_size:
                    # 如果数据不完整，尝试补齐（使用最后一个样本重复）
                    if len(output_data) > 0:
                        missing = output_size - len(output_data)
                        last_sample = output_data[-bytes_per_sample:]
                        output_data += last_sample * (missing // bytes_per_sample)
                        print(f"警告: ffmpeg 输出数据不完整，已补齐 (期望 {output_size} 字节，实际 {len(output_data)} 字节)")
                    else:
                        raise RuntimeError(f"ffmpeg 未输出任何数据 (期望 {output_size} 字节)")
                
                return output_data
                
            except BrokenPipeError:
                print("ffmpeg 管道断开，尝试重启")
                self._start_process()
                if self.process is None or self.process.poll() is not None:
                    self.enabled = False
                    raise RuntimeError("无法重启 ffmpeg 进程")
                raise RuntimeError("ffmpeg 管道错误，请重试")
            except Exception as e:
                print(f"ffmpeg 重采样错误: {e}")
                # 尝试重启进程
                try:
                    self._start_process()
                except:
                    self.enabled = False
                raise
    
    def close(self):
        """关闭 ffmpeg 进程"""
        with self.lock:
            if self.process:
                try:
                    self.process.stdin.close()
                except:
                    pass
                try:
                    self.process.stdout.close()
                except:
                    pass
                try:
                    self.process.terminate()
                    self.process.wait(timeout=1)
                except:
                    try:
                        self.process.kill()
                    except:
                        pass
                self.process = None
            self.enabled = False

class AudioProcessor:
    """音频数据处理器"""
    
    @staticmethod
    def bytes_to_numpy(audio_data: bytes, dtype: str = "int16") -> np.ndarray:
        """
        将字节数据转换为numpy数组
        
        Args:
            audio_data: 音频字节数据
            dtype: 数据类型
            
        Returns:
            numpy数组
        """
        if dtype == "int16":
            return np.frombuffer(audio_data, dtype=np.int16)
        elif dtype == "int32":
            return np.frombuffer(audio_data, dtype=np.int32)
        elif dtype == "float32":
            return np.frombuffer(audio_data, dtype=np.float32)
        else:
            return np.frombuffer(audio_data, dtype=np.int16)
    
    @staticmethod
    def numpy_to_bytes(audio_data: np.ndarray, dtype: str = "int16") -> bytes:
        """
        将numpy数组转换为字节数据
        
        Args:
            audio_data: numpy数组
            dtype: 数据类型
            
        Returns:
            字节数据
        """
        if dtype == "int16":
            return audio_data.astype(np.int16).tobytes()
        elif dtype == "int32":
            return audio_data.astype(np.int32).tobytes()
        elif dtype == "float32":
            return audio_data.astype(np.float32).tobytes()
        else:
            return audio_data.astype(np.int16).tobytes()
    
    @staticmethod
    def resample(audio_data: np.ndarray, 
                 original_rate: int, 
                 target_rate: int,
                 resampler: Optional[FFmpegResampler] = None) -> np.ndarray:
        """
        重采样音频数据
        
        Args:
            audio_data: 原始音频数据
            original_rate: 原始采样率
            target_rate: 目标采样率
            resampler: FFmpegResampler 实例（如果提供，使用 ffmpeg 重采样）
            
        Returns:
            重采样后的音频数据
        """
        if original_rate == target_rate:
            return audio_data
        
        # 如果提供了 ffmpeg 重采样器，尝试使用它
        if resampler is not None and resampler.enabled:
            try:
                # 转换为字节
                audio_bytes = audio_data.tobytes()
                # 使用 ffmpeg 重采样
                resampled_bytes = resampler.resample(audio_bytes)
                # 转换回 numpy 数组
                return np.frombuffer(resampled_bytes, dtype=audio_data.dtype)
            except Exception as e:
                # ffmpeg 失败，回退到简单插值
                print(f"ffmpeg 重采样失败，回退到简单插值: {e}")
                return AudioProcessor._resample_simple(audio_data, original_rate, target_rate)
        else:
            # 使用简单插值
            return AudioProcessor._resample_simple(audio_data, original_rate, target_rate)
    
    @staticmethod
    def _resample_simple(audio_data: np.ndarray,
                        original_rate: int,
                        target_rate: int) -> np.ndarray:
        """
        简单的线性插值重采样（回退方法）
        
        Args:
            audio_data: 原始音频数据
            original_rate: 原始采样率
            target_rate: 目标采样率
            
        Returns:
            重采样后的音频数据
        """
        # 计算重采样比例
        ratio = target_rate / original_rate
        original_length = len(audio_data)
        target_length = int(original_length * ratio)
        
        # 使用numpy的插值进行简单重采样
        indices = np.linspace(0, original_length - 1, target_length)
        resampled = np.interp(indices, np.arange(original_length), audio_data)
        
        return resampled.astype(audio_data.dtype)
    
    @staticmethod
    def normalize(audio_data: np.ndarray, target_max: float = 1.0) -> np.ndarray:
        """
        归一化音频数据
        
        Args:
            audio_data: 音频数据
            target_max: 目标最大值
            
        Returns:
            归一化后的音频数据
        """
        if len(audio_data) == 0:
            return audio_data
        
        max_val = np.max(np.abs(audio_data))
        if max_val == 0:
            return audio_data
        
        normalized = audio_data.astype(np.float32) / max_val * target_max
        return normalized.astype(audio_data.dtype)
    
    @staticmethod
    def calculate_volume(audio_data: bytes, dtype: str = "int16", channels: int = 1) -> float:
        """
        计算音频数据的音量（RMS值，转换为分贝）
        
        Args:
            audio_data: 音频字节数据
            dtype: 数据类型
            channels: 声道数（如果>1，会先转换为单声道）
            
        Returns:
            音量值（0-100的百分比）
        """
        if len(audio_data) == 0:
            return 0.0
        
        # 转换为numpy数组
        audio_array = AudioProcessor.bytes_to_numpy(audio_data, dtype)
        
        # 如果是多声道，先转换为单声道
        if channels > 1:
            try:
                audio_array = AudioProcessor.convert_to_mono(audio_array, channels)
            except Exception as e:
                # 如果转换失败，假设已经是单声道
                pass
        
        # 转换为浮点数（-1.0到1.0范围）
        if dtype == "int16":
            audio_float = audio_array.astype(np.float32) / 32768.0
        elif dtype == "int32":
            audio_float = audio_array.astype(np.float32) / 2147483648.0
        elif dtype == "float32":
            audio_float = audio_array.astype(np.float32)
        else:
            audio_float = audio_array.astype(np.float32) / 32768.0
        
        # 计算RMS（均方根）
        rms = np.sqrt(np.mean(audio_float ** 2))
        
        # 也计算峰值（更敏感）
        peak = np.max(np.abs(audio_float))
        
        # 使用RMS和峰值的组合来计算音量
        # 如果RMS很小但峰值较大，说明有突发音频
        # 使用两者的加权平均
        if rms > 0 or peak > 0:
            # 将RMS和峰值都转换为0-100的百分比（线性）
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
        else:
            volume = 0.0
        
        return volume
    
    @staticmethod
    def convert_to_mono(audio_data: np.ndarray, channels: int = 2) -> np.ndarray:
        """
        将多声道音频转换为单声道
        
        Args:
            audio_data: 音频数据（一维数组，包含所有声道的数据）
            channels: 原始声道数
            
        Returns:
            单声道音频数据
        """
        if channels == 1:
            return audio_data
        
        # 重塑为 (samples, channels) 形状
        samples = len(audio_data) // channels
        if samples == 0:
            return audio_data
        
        reshaped = audio_data.reshape(samples, channels)
        
        # 取平均值转换为单声道
        mono = np.mean(reshaped, axis=1)
        
        return mono.astype(audio_data.dtype)


