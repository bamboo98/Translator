"""
Vosk语音识别引擎
"""
import json
import os
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Tuple
from vosk import Model, KaldiRecognizer, SpkModel, SetLogLevel
import threading
import queue
import numpy as np

class VoskEngine:
    """Vosk语音识别引擎类"""
    
    def __init__(self, 
                 model_path: str = "models",
                 language: str = "zh",
                 sample_rate: int = 16000,
                 callback: Optional[Callable[[str, bool, Optional[List[float]], Optional[int], str], None]] = None):
        """
        初始化Vosk识别引擎
        
        Args:
            model_path: 模型存放目录
            language: 语言代码（zh, en, ja, ko等）
            sample_rate: 采样率
            callback: 识别结果回调函数 (text, is_final, spk_embedding, speaker_id, feature_hash)
        """
        self.model_path = Path(model_path)
        self.language = language
        self.sample_rate = sample_rate
        self.callback = callback
        
        self.model: Optional[Model] = None
        self.spk_model: Optional[SpkModel] = None  # 说话人识别模型
        self.recognizer: Optional[KaldiRecognizer] = None
        self.is_processing = False
        self.audio_queue = queue.Queue()
        self.processing_thread: Optional[threading.Thread] = None
        
        # 说话人识别相关
        self.speaker_profiles: Dict[int, List[float]] = {}  # {speaker_id: embedding}
        self.speaker_embeddings_history: List[tuple] = []  # [(embedding, text), ...] 存储至少2句话的嵌入
        self.min_sentences_for_speaker_id = 2  # 至少需要2句话才开始说话人识别
        self.similarity_threshold = 0.5  # 说话人相似度阈值（降低以提高匹配率）
        self.next_speaker_id = 1
        self.speaker_id_enabled = False  # 是否启用说话人识别功能（取决于说话人模型是否加载成功）
        # 注意：如果speaker_id_enabled=False，所有说话人ID将视为1，但不会显示（因为只有一个说话人）
        
        # 设置Vosk日志级别为-1（关闭所有日志）
        try:
            SetLogLevel(-1)
        except:
            pass
        
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
            # 卸载旧模型（确保数据干净）
            if self.recognizer:
                self.recognizer = None
            if self.model:
                self.model = None
            if self.spk_model:
                self.spk_model = None
            
            # 清空说话人识别相关数据
            self.speaker_profiles.clear()
            self.speaker_embeddings_history.clear()
            self.next_speaker_id = 1
            self.speaker_id_enabled = False  # 默认不启用
            
            # 加载语言识别模型
            print(f"正在加载语言模型: {model_dir}")
            self.model = Model(str(model_dir))
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)  # 启用词级时间戳
            
            # 加载说话人识别模型（使用SpkModel类，不是Model类）
            spk_model_path = self.model_path / "vosk-model-spk-0.4"
            if spk_model_path.exists() and spk_model_path.is_dir():
                # 检查spk模型必需的文件
                required_files = ["final.ext.raw", "mean.vec", "transform.mat", "mfcc.conf"]
                has_all_files = all((spk_model_path / f).exists() for f in required_files)
                
                if has_all_files:
                    print(f"正在加载说话人识别模型: {spk_model_path}")
                    try:
                        self.spk_model = SpkModel(str(spk_model_path))
                        self.recognizer.SetSpkModel(self.spk_model)
                        self.speaker_id_enabled = True  # 说话人模型加载成功，启用说话人识别
                        print("说话人识别模型加载成功，说话人识别功能已启用")
                    except Exception as e:
                        print(f"加载说话人识别模型失败: {e}")
                        self.spk_model = None
                        self.speaker_id_enabled = False
                        print("说话人识别功能已禁用（模型加载失败）")
                else:
                    print(f"警告: 说话人识别模型目录存在但缺少必需文件，说话人识别功能将不可用")
                    print(f"需要的文件: {', '.join(required_files)}")
                    self.spk_model = None
                    self.speaker_id_enabled = False
                    print("说话人识别功能已禁用（缺少必需文件）")
            else:
                print(f"提示: 未找到说话人识别模型 {spk_model_path}，说话人识别功能将不可用")
                self.spk_model = None
                self.speaker_id_enabled = False
                print("说话人识别功能已禁用（模型不存在），所有说话人ID将视为1")
            
            print(f"模型加载成功: {self.language}")
            return True
            
        except Exception as e:
            print(f"加载模型失败: {e}")
            self.model = None
            self.spk_model = None
            self.recognizer = None
            import traceback
            traceback.print_exc()
            return False
    
    def start(self) -> None:
        """开始识别处理"""
        # 2025-12-29: 调试输出 - 启动检查
        if self.is_processing:
            print(f"[WARNING 2025-12-29] Vosk引擎已在处理状态，无需重复启动")
            return
        
        if not self.recognizer:
            print(f"[ERROR 2025-12-29] 模型未加载，无法开始识别")
            return
        
        # 2025-12-29: 调试输出 - 启动信息
        print(f"[DEBUG 2025-12-29] 启动Vosk识别引擎 - 采样率: {self.sample_rate}Hz, 模型语言: {self.language}, 说话人识别: {'启用' if self.speaker_id_enabled else '禁用'}")
        
        self.is_processing = True
        self.processing_thread = threading.Thread(target=self._process_audio, daemon=True)
        self.processing_thread.start()
        
        # 重置计数器
        if hasattr(self, '_feed_count'):
            self._feed_count = 0
        
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
        # 2025-12-29: 调试输出 - 音频数据接收检查
        if not audio_data or len(audio_data) == 0:
            print(f"[WARNING 2025-12-29] Vosk引擎收到空音频数据，跳过")
            return
        
        if not self.is_processing:
            print(f"[WARNING 2025-12-29] Vosk引擎未在处理状态 (is_processing={self.is_processing})，无法接收音频数据 (长度: {len(audio_data)} 字节)")
            return
        
        if not self.recognizer:
            print(f"[WARNING 2025-12-29] Vosk识别器未初始化，无法接收音频数据 (长度: {len(audio_data)} 字节)")
            return
        
        # 2025-12-29: 调试输出 - 音频数据入队
        try:
            self.audio_queue.put(audio_data)
            # 2025-12-29: 调试输出 - 队列状态（每100个数据块输出一次，避免日志过多）
            if hasattr(self, '_feed_count'):
                self._feed_count += 1
            else:
                self._feed_count = 1
            
            if self._feed_count % 100 == 0:
                queue_size = self.audio_queue.qsize()
                print(f"[DEBUG 2025-12-29] Vosk引擎已接收 {self._feed_count} 个音频块，当前队列大小: {queue_size}, 最新块长度: {len(audio_data)} 字节")
        except Exception as e:
            print(f"[ERROR 2025-12-29] 音频数据入队失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)
    
    def _embedding_to_hash(self, embedding: List[float]) -> str:
        """
        将特征向量转换为简短的哈希字符串（用于显示）
        
        Args:
            embedding: 说话人特征向量
            
        Returns:
            特征码字符串（前8个维度的简化表示）
        """
        if not embedding or len(embedding) == 0:
            return ""
        
        # 取前8个维度，转换为整数并格式化为字符串
        # 使用前8个维度的符号和绝对值的前2位数字
        hash_parts = []
        for i in range(min(8, len(embedding))):
            val = embedding[i]
            # 取符号和绝对值的前2位
            sign = "+" if val >= 0 else "-"
            abs_val = abs(val)
            # 转换为0-99的整数
            int_val = min(99, int(abs_val * 10))
            hash_parts.append(f"{sign}{int_val:02d}")
        
        return "".join(hash_parts)
    
    def _identify_speaker(self, embedding: List[float]) -> Tuple[Optional[int], str]:
        """
        识别说话人
        
        Args:
            embedding: 说话人特征向量
            
        Returns:
            (说话人ID, 特征码) 的元组，如果无法识别返回 (None, "")
        """
        if not embedding or len(embedding) == 0:
            return None, ""
        
        # 生成特征码
        feature_hash = self._embedding_to_hash(embedding)
        
        # 如果还没有足够的句子，不进行说话人识别
        if len(self.speaker_embeddings_history) < self.min_sentences_for_speaker_id:
            return None, feature_hash
        
        # 如果还没有说话人档案，创建第一个
        if len(self.speaker_profiles) == 0:
            # 第一个说话人
            speaker_id = self.next_speaker_id
            self.speaker_profiles[speaker_id] = embedding.copy()
            self.next_speaker_id += 1
            return speaker_id, feature_hash
        
        # 与已有说话人比较（使用所有历史嵌入的平均值）
        best_match = None
        max_similarity = 0.0
        
        for speaker_id, profile_embedding in self.speaker_profiles.items():
            similarity = self._cosine_similarity(embedding, profile_embedding)
            if similarity > max_similarity:
                max_similarity = similarity
                best_match = speaker_id
        
        # 如果相似度足够高，认为是同一说话人
        # 使用更低的阈值，并考虑历史相似度
        if max_similarity >= self.similarity_threshold:
            # 更新说话人特征（滑动平均，更倾向于保留历史特征）
            alpha = 0.1  # 新特征权重较小，更稳定
            self.speaker_profiles[best_match] = [
                (1 - alpha) * self.speaker_profiles[best_match][i] + alpha * embedding[i]
                for i in range(len(embedding))
            ]
            return best_match, feature_hash
        else:
            # 新说话人（但需要更严格的判断）
            # 如果相似度太低（<0.3），才认为是新说话人
            if max_similarity < 0.3:
                speaker_id = self.next_speaker_id
                self.speaker_profiles[speaker_id] = embedding.copy()
                self.next_speaker_id += 1
                return speaker_id, feature_hash
            else:
                # 相似度在0.3-0.5之间，可能是同一说话人但特征有变化
                # 更新特征但保持ID
                alpha = 0.15
                self.speaker_profiles[best_match] = [
                    (1 - alpha) * self.speaker_profiles[best_match][i] + alpha * embedding[i]
                    for i in range(len(embedding))
                ]
                return best_match, feature_hash
    
    def _process_audio(self) -> None:
        """音频处理线程"""
        # 2025-12-29: 调试输出 - 处理线程启动
        print(f"[DEBUG 2025-12-29] Vosk音频处理线程已启动")
        processed_count = 0
        
        while self.is_processing:
            try:
                # 从队列获取音频数据
                audio_data = self.audio_queue.get(timeout=0.1)
                processed_count += 1
                
                # 2025-12-29: 调试输出 - 音频数据处理（每50个数据块输出一次）
                if processed_count % 50 == 0:
                    print(f"[DEBUG 2025-12-29] Vosk引擎已处理 {processed_count} 个音频块，当前块长度: {len(audio_data)} 字节")
                
                if not self.recognizer:
                    print(f"[WARNING 2025-12-29] Vosk识别器未初始化，跳过音频数据处理")
                    continue
                
                # 识别音频
                if self.recognizer.AcceptWaveform(audio_data):
                    # 最终结果
                    result = json.loads(self.recognizer.Result())
                    text = result.get('text', '').strip()
                    spk = result.get('spk', None)  # 说话人特征向量
                    
                    # 2025-12-29: 调试输出 - 最终识别结果
                    if text:
                        print(f"[DEBUG 2025-12-29] Vosk最终识别结果: '{text}' (长度: {len(text)} 字符)")
                    else:
                        print(f"[WARNING 2025-12-29] Vosk最终识别结果为空")
                    
                    if text:
                        speaker_id = None
                        feature_hash = ""
                        
                        # 如果启用了说话人识别功能且获取到了特征向量，进行说话人识别
                        if self.speaker_id_enabled and self.spk_model and spk:
                            # 保存嵌入历史（用于后续识别）
                            self.speaker_embeddings_history.append((spk, text))
                            # 只保留最近的嵌入（避免内存增长）
                            if len(self.speaker_embeddings_history) > 10:
                                self.speaker_embeddings_history.pop(0)
                            
                            # 识别说话人（返回ID和特征码）
                            speaker_id, feature_hash = self._identify_speaker(spk)
                        elif not self.speaker_id_enabled:
                            # 如果说话人识别功能未启用，所有说话人ID视为1
                            # 但不添加到speaker_profiles，这样就不会显示说话人ID（因为只有一个说话人）
                            speaker_id = 1
                        
                        if self.callback:
                            # 2025-12-29: 调试输出 - 准备调用回调
                            print(f"[DEBUG 2025-12-29] 准备调用识别结果回调 - 文本: '{text}', 说话人ID: {speaker_id}")
                            self.callback(text, True, spk, speaker_id, feature_hash)
                            print(f"[DEBUG 2025-12-29] 识别结果回调调用成功")
                        else:
                            print(f"[WARNING 2025-12-29] 识别结果回调函数未设置，无法传递识别结果")
                else:
                    # 部分结果
                    result = json.loads(self.recognizer.PartialResult())
                    text = result.get('partial', '').strip()
                    spk = result.get('spk', None)
                    
                    # 2025-12-29: 调试输出 - 部分识别结果（每20个输出一次，避免日志过多）
                    if processed_count % 20 == 0:
                        if text:
                            print(f"[DEBUG 2025-12-29] Vosk部分识别结果: '{text}' (长度: {len(text)} 字符)")
                        else:
                            print(f"[DEBUG 2025-12-29] Vosk部分识别结果为空 (已处理 {processed_count} 个音频块)")
                    
                    if text and self.callback:
                        # 部分结果不进行说话人识别，但可以生成特征码用于显示
                        feature_hash = ""
                        if spk:
                            feature_hash = self._embedding_to_hash(spk)
                        self.callback(text, False, spk, None, feature_hash)
                        
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ERROR 2025-12-29] Vosk音频处理错误: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # 2025-12-29: 调试输出 - 处理线程结束
        print(f"[DEBUG 2025-12-29] Vosk音频处理线程已结束，共处理 {processed_count} 个音频块")


