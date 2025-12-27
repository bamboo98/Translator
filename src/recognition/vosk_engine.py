"""
Vosk语音识别引擎
"""
import json
import os
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from vosk import Model, KaldiRecognizer
import threading
import queue

class VoskEngine:
    """Vosk语音识别引擎类"""
    
    def __init__(self, 
                 model_path: str = "models",
                 language: str = "zh",
                 sample_rate: int = 16000,
                 callback: Optional[Callable[[str, bool], None]] = None):
        """
        初始化Vosk识别引擎
        
        Args:
            model_path: 模型存放目录
            language: 语言代码（zh, en, ja, ko等）
            sample_rate: 采样率
            callback: 识别结果回调函数 (text, is_final)
        """
        self.model_path = Path(model_path)
        self.language = language
        self.sample_rate = sample_rate
        self.callback = callback
        
        self.model: Optional[Model] = None
        self.recognizer: Optional[KaldiRecognizer] = None
        self.is_processing = False
        self.audio_queue = queue.Queue()
        self.processing_thread: Optional[threading.Thread] = None
        
        # 加载模型
        self.load_model()
    
    def _find_model(self, language: str) -> Optional[Path]:
        """
        查找指定语言的模型
        
        Args:
            language: 语言代码
            
        Returns:
            模型路径，如果未找到返回None
        """
        # 语言代码映射（配置中的语言代码 -> 模型文件名中的语言代码）
        language_map = {
            "zh": "cn",  # 中文：配置用zh，模型文件名用cn
            "en": "en-us",  # 英文：配置用en，模型文件名可能是en-us
            "ja": "ja",  # 日文
            "ko": "ko",  # 韩文
            "ru": "ru",  # 俄文
        }
        
        # 获取模型文件名中使用的语言代码
        model_lang = language_map.get(language, language)
        
        # 常见的模型命名模式（支持带版本号）
        possible_names = [
            f"vosk-model-{model_lang}-0.22",  # 带版本号（0.22版本）
            f"vosk-model-{model_lang}-0.42",  # 带版本号（0.42版本）
            f"vosk-model-{model_lang}",  # 不带版本号
            f"vosk-model-small-{model_lang}-0.22",  # small版本
            f"vosk-model-small-{model_lang}",  # small版本不带版本号
            f"model-{model_lang}",  # 简化命名
            model_lang,  # 直接使用语言代码
            # 也尝试原始语言代码（如果映射失败）
            f"vosk-model-{language}-0.22",
            f"vosk-model-{language}",
        ]
        
        for name in possible_names:
            model_dir = self.model_path / name
            if model_dir.exists() and model_dir.is_dir():
                # 检查是否包含必要的文件
                if (model_dir / "am" / "final.mdl").exists() or \
                   (model_dir / "conf" / "model.conf").exists():
                    return model_dir
        
        # 如果精确匹配失败，尝试模糊匹配（查找包含语言代码的目录）
        if self.model_path.exists():
            for item in self.model_path.iterdir():
                if item.is_dir():
                    # 检查目录名是否包含语言代码
                    dir_name_lower = item.name.lower()
                    if (model_lang in dir_name_lower or language in dir_name_lower) and \
                       "vosk-model" in dir_name_lower:
                        # 验证是否是有效的模型目录
                        if (item / "am" / "final.mdl").exists() or \
                           (item / "conf" / "model.conf").exists():
                            return item
        
        return None
    
    def load_model(self, language: Optional[str] = None) -> bool:
        """
        加载Vosk模型
        
        Args:
            language: 语言代码或模型文件夹名称，如果为None则使用当前语言
            
        Returns:
            是否加载成功
        """
        if language:
            self.language = language
        
        # 首先尝试直接使用文件夹名称
        model_dir = self.model_path / self.language
        if model_dir.exists() and model_dir.is_dir():
            # 验证是否是有效的模型目录
            if (model_dir / "am" / "final.mdl").exists() or \
               (model_dir / "conf" / "model.conf").exists():
                # 直接使用这个目录
                pass
            else:
                model_dir = None
        else:
            model_dir = None
        
        # 如果直接查找失败，使用原来的查找逻辑
        if model_dir is None:
            model_dir = self._find_model(self.language)
        
        if model_dir is None:
            print(f"警告: 未找到语言模型 '{self.language}'，请确保模型已下载到 {self.model_path}")
            print(f"模型下载地址: https://alphacephei.com/vosk/models")
            return False
        
        try:
            # 卸载旧模型
            if self.recognizer:
                self.recognizer = None
            if self.model:
                self.model = None
            
            # 加载新模型
            print(f"正在加载模型: {model_dir}")
            self.model = Model(str(model_dir))
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)  # 启用词级时间戳
            
            print(f"模型加载成功: {self.language}")
            return True
            
        except Exception as e:
            print(f"加载模型失败: {e}")
            self.model = None
            self.recognizer = None
            return False
    
    def start(self) -> None:
        """开始识别处理"""
        if self.is_processing:
            return
        
        if not self.recognizer:
            print("错误: 模型未加载，无法开始识别")
            return
        
        self.is_processing = True
        self.processing_thread = threading.Thread(target=self._process_audio, daemon=True)
        self.processing_thread.start()
        print("Vosk识别引擎已启动")
    
    def stop(self) -> None:
        """停止识别处理"""
        if not self.is_processing:
            return
        
        self.is_processing = False
        
        # 清空队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except:
                break
        
        if self.processing_thread:
            self.processing_thread.join(timeout=2.0)
        
        print("Vosk识别引擎已停止")
    
    def feed_audio(self, audio_data: bytes) -> None:
        """
        输入音频数据
        
        Args:
            audio_data: 音频字节数据
        """
        if self.is_processing and self.recognizer:
            self.audio_queue.put(audio_data)
    
    def _process_audio(self) -> None:
        """音频处理线程"""
        while self.is_processing:
            try:
                # 从队列获取音频数据
                audio_data = self.audio_queue.get(timeout=0.1)
                
                if not self.recognizer:
                    continue
                
                # 识别音频
                if self.recognizer.AcceptWaveform(audio_data):
                    # 最终结果
                    result = json.loads(self.recognizer.Result())
                    text = result.get('text', '').strip()
                    if text and self.callback:
                        self.callback(text, True)
                else:
                    # 部分结果
                    result = json.loads(self.recognizer.PartialResult())
                    text = result.get('partial', '').strip()
                    if text and self.callback:
                        self.callback(text, False)
                        
            except queue.Empty:
                continue
            except Exception as e:
                print(f"音频处理错误: {e}")
                import traceback
                traceback.print_exc()
                continue


