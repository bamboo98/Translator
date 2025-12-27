"""
音频预处理模块
"""
import numpy as np
from typing import Union

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
                 target_rate: int) -> np.ndarray:
        """
        重采样音频数据（简单线性插值方法）
        
        注意：对于生产环境，建议使用librosa或scipy.signal.resample
        
        Args:
            audio_data: 原始音频数据
            original_rate: 原始采样率
            target_rate: 目标采样率
            
        Returns:
            重采样后的音频数据
        """
        if original_rate == target_rate:
            return audio_data
        
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


