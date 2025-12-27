"""
配置文件管理模块
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

class Config:
    """配置管理类"""
    
    DEFAULT_CONFIG = {
        "audio": {
            "sample_rate": 16000,
            "channels": 1,
            "chunk_size": 1024,
            "format": "int16",
            "device_index": None  # None表示自动查找CABLE设备
        },
        "vosk": {
            "model_path": "models",
            "language": "zh"  # 默认中文（实际使用模型文件夹名称）
        },
        "translation": {
            "api_provider": "siliconflow",  # 硅基流动
            "api_key": "",
            "api_url": "https://api.siliconflow.cn/v1/chat/completions",
            "model": "deepseek-ai/DeepSeek-V3",
            "timeout": 30,
            "max_tokens": 8000,  # 最大token数
            "temperature": 0.3,  # 温度参数
            "memory_max_count": 6,  # 记忆最大条数
            "memory_time": 300,  # 记忆时间（秒），默认5分钟
            "prompt_template": "你是一个为VRChat提供实时翻译的专业同声传译助手\n- 翻译成口语化的中文,保留语气词,前文和上一句无需翻译\n- 原文为语音识别,可能存在断句问题和同/近音词错误,结合上下文推测完整且正确的语句\n- 在翻译结果开头添加0~99的整数和分隔符|来表示该段翻译的重要性,越大会在前文中保留越久,供后文翻译参考\n- 输出格式:重要性数值|翻译结果,不需要任何解释或备注,推测的翻译部分加上括号\n\n前文参考:\n{context}\n\n上一句是:{last}\n\n待翻译内容:\n{text}",
            "instant_prompt_template": "翻译成中文,不完整的部分使用...代替,只输出翻译结果,不需要任何解释或备注:\n{text}",
            "instant_translate": False  # 是否启用即时翻译
        }
    }
    
    def __init__(self, config_file: str = "config.json"):
        """
        初始化配置
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = Path(config_file)
        self.config = self.DEFAULT_CONFIG.copy()
        self.load()
    
    def load(self) -> None:
        """从文件加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self._merge_config(self.config, loaded_config)
            except Exception as e:
                print(f"加载配置文件失败: {e}，使用默认配置")
    
    def save(self) -> None:
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def _merge_config(self, base: Dict, update: Dict) -> None:
        """递归合并配置字典"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号分隔的路径
        
        Args:
            key_path: 配置路径，如 "audio.sample_rate"
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key_path.split('.')
        value = self.config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key_path: str, value: Any) -> None:
        """
        设置配置值
        
        Args:
            key_path: 配置路径
            value: 配置值
        """
        keys = key_path.split('.')
        config = self.config
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value
    
    def get_audio_config(self) -> Dict[str, Any]:
        """获取音频配置"""
        return self.config["audio"]
    
    def get_vosk_config(self) -> Dict[str, Any]:
        """获取Vosk配置"""
        return self.config["vosk"]
    
    def get_translation_config(self) -> Dict[str, Any]:
        """获取翻译配置"""
        return self.config["translation"]


