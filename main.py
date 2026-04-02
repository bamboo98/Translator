"""
VR翻译器主程序
整合音频捕获、语音识别、翻译和VR显示功能
"""
import sys
import threading
from typing import Optional
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, pyqtSlot, QMetaObject, Qt

from config import Config
from src.audio.capture_cable import AudioCapture
from src.audio.capture_loopback import LoopbackAudioCapture
from src.recognition.vosk_engine import VoskEngine
from src.recognition.live_captions_engine import LiveCaptionsEngine
from src.translation.api_client import TranslationClient
from src.translation.context_manager import WeightedContextManager
from src.ui.main_window import MainWindow
import psutil
import subprocess
import os

class TranslatorApp:
    """翻译器应用主类"""
    
    def __init__(self):
        """初始化应用"""
        self.config = Config()
        
        # 初始化各个模块
        self.audio_capture: Optional[AudioCapture] = None
        self.loopback_capture: Optional[LoopbackAudioCapture] = None
        self.vosk_engine: Optional[VoskEngine] = None
        self.live_captions_engine: Optional[LiveCaptionsEngine] = None
        self.translation_client: Optional[TranslationClient] = None
        # 初始化上下文管理器（使用配置）
        trans_config = self.config.get_translation_config()
        max_count = trans_config.get("memory_max_count", 10)
        memory_time = trans_config.get("memory_time", 300.0)
        self.context_manager = WeightedContextManager(max_count=max_count, memory_time=memory_time)
        
        # 状态
        self.is_listening = False
        self.is_recognizing = False
        self.is_translating = False
        self.model_loaded = False
        self.current_text = ""
        # 从配置加载识别方式
        self.recognition_method = self.config.get("recognition.method", 0)  # 0=Vosk, 1=LiveCaptions
        self.last_instant_translate_time = 0.0  # 上次即时翻译请求时间
        
        # 翻译请求状态管理（事件驱动模式）
        self.pending_translate_request: Optional[dict] = None  # 等待中的请求：{"text": str, "type": "instant"/"full", "context_prompt": str, "last_text": str, "speaker_id": Optional[int]}
        self.is_waiting_for_response = False  # 是否正在等待上一个请求返回
        self.last_translate_time = 0.0  # 上次翻译完成时间
        self.translate_thread: Optional[threading.Thread] = None  # 常驻翻译工作线程
        self.translate_thread_stop = threading.Event()  # 用于停止线程
        self.translate_request_event = threading.Event()  # 用于通知有新请求
        self.translate_thread_running = False  # 线程运行状态
        self.translate_times = []  # 最近20次翻译请求的耗时列表
        
        # 创建GUI
        self.app = QApplication(sys.argv)
        
        # 强制应用暗色主题，不依赖系统主题
        self.app.setStyle("Fusion")  # 使用Fusion样式，跨平台一致
        # 设置全局暗色主题样式表
        self.app.setStyleSheet("""
            QApplication {
                color: #d4d4d4;
                background-color: #2b2b2b;
            }
            QWidget {
                color: #d4d4d4;
                background-color: #2b2b2b;
            }
            QMenuBar {
                background-color: #2b2b2b;
                color: #d4d4d4;
            }
            QMenuBar::item {
                background-color: transparent;
            }
            QMenuBar::item:selected {
                background-color: #3c3c3c;
            }
            QMenu {
                background-color: #2b2b2b;
                color: #d4d4d4;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background-color: #3c3c3c;
            }
            QToolTip {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #555;
            }
            QScrollBar:vertical {
                background-color: #2b2b2b;
                width: 12px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
            QScrollBar:horizontal {
                background-color: #2b2b2b;
                height: 12px;
            }
            QScrollBar::handle:horizontal {
                background-color: #555;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #666;
            }
        """)
        
        self.window = MainWindow(self.config)
        
        # 连接信号
        self._connect_signals()
        
        # 初始化模块
        self._init_modules()
        
        # 初始化上下文信息更新定时器（必须在QApplication创建之后）
        self.context_info_timer = QTimer()
        self.context_info_timer.timeout.connect(self._update_context_info_tooltip)
        self.context_info_timer.start(1000)  # 每秒更新一次
        
        # 不再检查VR状态
    
    def _connect_signals(self) -> None:
        """连接信号和槽"""
        self.window.listen_start_signal.connect(self.start_listening)
        self.window.listen_stop_signal.connect(self.stop_listening)
        self.window.load_model_signal.connect(self.load_model)
        self.window.recognition_start_signal.connect(self.start_recognition)
        self.window.recognition_stop_signal.connect(self.stop_recognition)
        self.window.recognition_method_changed_signal.connect(self._on_recognition_method_changed)
        self.window.open_live_captions_signal.connect(self._on_open_live_captions)
        self.window.translation_start_signal.connect(self.start_translation)
        self.window.translation_stop_signal.connect(self.stop_translation)
        # 不再需要language_changed_signal，UI自己处理
        self.window.device_changed_signal.connect(self._on_device_changed)  # 保留兼容性
        self.window.input_device_changed_signal.connect(self._on_input_device_changed)
        self.window.loopback_device_changed_signal.connect(self._on_loopback_device_changed)
        self.window.device_type_changed_signal.connect(self._on_device_type_changed)
        self.window.volume_threshold_changed_signal.connect(self._on_volume_threshold_changed)
        self.window.refresh_devices_signal.connect(self._refresh_devices)
        self.window.volume_updated_signal.connect(self.window.update_volume)
        self.window.recognition_text_updated_signal.connect(self.window.update_recognition_text)
        self.window.translation_text_updated_signal.connect(self.window.update_translation_text)
        self.window.translation_latest_text_updated_signal.connect(self.window.update_translation_latest_text_only)
        self.window.instant_translate_changed_signal.connect(self._on_instant_translate_changed)
        self.window.manual_translate_signal.connect(self._on_manual_translate)
        self.window.status_message_signal.connect(self.window.show_status_message)
        self.window.apply_settings_signal.connect(self._on_apply_settings)
        self.window.clear_texts_signal.connect(self._on_clear_texts)
        self.window.update_used_chars_signal.connect(self._on_used_chars_updated)
        self.window.translation_status_updated_signal.connect(self.window.update_translation_status)
    
    def _init_modules(self) -> None:
        """初始化各个模块"""
        try:
            # 初始化音频捕获
            audio_config = self.config.get_audio_config()
            device_type = audio_config.get("device_type", "input")
            device_index = audio_config.get("device_index")
            loopback_device_index = audio_config.get("loopback_device_index")
            process_interval_seconds = audio_config.get("process_interval_seconds", 3.0)
            volume_threshold = audio_config.get("volume_threshold", 1.0)
            sentence_break_interval = audio_config.get("sentence_break_interval", 2.0)
            
            # 获取输入设备列表
            input_devices = []
            try:
                temp_capture = AudioCapture(
                    sample_rate=audio_config.get("sample_rate", 16000),
                    channels=audio_config.get("channels", 1),
                    process_interval_seconds=process_interval_seconds,
                    format=audio_config.get("format", "int16"),
                    device_index=None,  # 不指定设备，只用于获取列表
                    sentence_break_interval=sentence_break_interval
                )
                input_devices = temp_capture.get_available_devices()
                temp_capture.close()
            except Exception as e:
                print(f"获取输入设备列表失败: {e}")
            
            # 获取桌面音频设备列表
            loopback_devices = []
            try:
                temp_loopback = LoopbackAudioCapture(
                    sample_rate=audio_config.get("sample_rate", 16000),
                    channels=audio_config.get("channels", 1),
                    process_interval_seconds=process_interval_seconds,
                    format=audio_config.get("format", "int16"),
                    device_index=None,
                    sentence_break_interval=sentence_break_interval
                )
                loopback_devices = temp_loopback.get_available_devices()
                temp_loopback.close()
            except Exception as e:
                print(f"获取桌面音频设备列表失败: {e}")
            
            # 更新GUI设备列表
            self.window.update_device_list(
                input_devices, 
                loopback_devices,
                default_input_index=device_index,
                default_loopback_index=loopback_device_index,
                device_type=device_type
            )
            
            # 根据设备类型创建对应的捕获对象（但不立即启动）
            if device_type == "input" and device_index is not None:
                self.audio_capture = AudioCapture(
                    sample_rate=audio_config.get("sample_rate", 16000),
                    channels=audio_config.get("channels", 1),
                    process_interval_seconds=process_interval_seconds,
                    format=audio_config.get("format", "int16"),
                    callback=self._on_audio_chunk,
                    volume_callback=self._on_volume_update,
                    device_index=device_index,
                    volume_threshold=volume_threshold,
                    sentence_break_interval=sentence_break_interval
                )
            elif device_type == "loopback" and loopback_device_index is not None:
                self.loopback_capture = LoopbackAudioCapture(
                    sample_rate=audio_config.get("sample_rate", 16000),
                    channels=audio_config.get("channels", 1),
                    process_interval_seconds=process_interval_seconds,
                    format=audio_config.get("format", "int16"),
                    callback=self._on_audio_chunk,
                    volume_callback=self._on_volume_update,
                    device_index=loopback_device_index,
                    volume_threshold=volume_threshold,
                    sentence_break_interval=sentence_break_interval
                )
            
            # 不立即初始化Vosk引擎，等用户点击加载模型按钮
            self.vosk_engine: Optional[VoskEngine] = None
            
            # 初始化翻译客户端
            trans_config = self.config.get_translation_config()
            self.translation_client = TranslationClient(
                provider=trans_config.get("api_provider", "siliconflow"),
                api_key=trans_config.get("api_key", ""),
                api_url=trans_config.get("api_url", ""),
                model=trans_config.get("model", "deepseek-chat"),
                timeout=trans_config.get("timeout", 30),
                trans_config=trans_config  # 传递配置以便访问提示词模板
            )
            
            # 不再初始化VR Overlay
            self.vr_overlay = None
            
            print("所有模块初始化完成")
            
        except Exception as e:
            print(f"模块初始化失败: {e}")
            self.window.show_error("初始化错误", f"模块初始化失败: {e}")
    
    def _on_audio_chunk(self, audio_data: bytes) -> None:
        """音频块回调（累积的音频数据，约3秒）"""
        if not audio_data or len(audio_data) == 0:
            return
        
        if self.vosk_engine and self.is_recognizing:
            # 将累积的音频块传递给Vosk引擎
            # 注意：Vosk需要实时流，这里需要将块拆分成更小的块
            chunk_size = 4000  # Vosk推荐的大小
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i+chunk_size]
                if len(chunk) > 0:
                    self.vosk_engine.feed_audio(chunk)
    
    def _on_volume_update(self, volume: float) -> None:
        """音量更新回调（在音频捕获线程中调用）"""
        # 直接使用信号emit（信号是线程安全的）
        self.window.volume_updated_signal.emit(volume)
    
    def _on_recognition_result(self, text: str, is_final: bool, spk_embedding: Optional[list] = None, speaker_id: Optional[int] = None, feature_hash: str = "") -> None:
        """识别结果回调（可能在非主线程中调用）"""
        if not text or not text.strip():
            return
        
        # 实时字幕不需要过滤the，直接跳过
        if self.recognition_method == 1:  # LiveCaptions
            pass  # 实时字幕不需要过滤
        else:
            # Vosk识别：获取当前模型文件夹名称，检查是否是英语模型
            vosk_config = self.config.get_vosk_config()
            current_model = vosk_config.get("language", "")
            
            # 过滤英语模型的无效识别结果 'the'
            # 检查模型文件夹名称是否包含英语相关关键词
            if current_model and ("en" in current_model.lower() or "english" in current_model.lower()):
                text_stripped = text.strip().lower()
                if text_stripped == "the":
                    return  # 忽略无效的 'the' 识别结果
        
        # 检查是否有多个说话人（至少2个），只有多个说话人才显示标识
        display_speaker_id = None
        display_feature_hash = ""
        if is_final and speaker_id is not None:
            # 实时字幕的speaker_id始终为1，不显示
            if self.recognition_method == 1:  # LiveCaptions
                display_speaker_id = None  # 实时字幕不显示说话人ID
            elif self.vosk_engine and hasattr(self.vosk_engine, 'speaker_profiles') and len(self.vosk_engine.speaker_profiles) > 1:
                display_speaker_id = speaker_id
                display_feature_hash = feature_hash
        
        # 直接使用信号emit（信号是线程安全的）
        # 传递原始文本、说话人ID和特征码，让UI层决定如何显示
        self.window.recognition_text_updated_signal.emit(text, is_final, display_speaker_id, display_feature_hash)
        
        if self.is_translating:
            if is_final:
                # 完整句子翻译
                self.current_text = text
                context_prompt = self.context_manager.get_context()
                last_text = self.context_manager.get_last_text()
                self._request_translate(text, "full", context_prompt, last_text, display_speaker_id)
            else:
                # 部分结果：检查是否启用即时翻译
                trans_config = self.config.get_translation_config()
                instant_translate_enabled = trans_config.get("instant_translate", False)
                if instant_translate_enabled:
                    import time
                    current_time = time.time()
                    instant_interval = trans_config.get("instant_translate_interval", 3.5)
                    trigger_chars = trans_config.get("instant_translate_trigger_chars", 8)
                    
                    # 检查间隔时间
                    if current_time - self.last_instant_translate_time < instant_interval:
                        return  # 间隔时间未到，不触发即时翻译
                    
                    # 检查触发字数
                    should_trigger = False
                    # 检查是否是英文（只含常规ASCII字符）
                    is_english = all(ord(c) < 128 and (c.isalnum() or c.isspace() or c in ".,!?;:'\"-") for c in text)
                    
                    if is_english:
                        # 英文：按单词数计算（空格数+1）
                        word_count = len([w for w in text.split() if w.strip()])
                        should_trigger = word_count >= trigger_chars
                    else:
                        # 非英文：按UTF-8字符数计算
                        text_utf8_len = len(text.encode('utf-8'))
                        should_trigger = text_utf8_len > trigger_chars
                    
                    if should_trigger:
                        # 即时翻译请求
                        self.last_instant_translate_time = current_time
                        self._request_translate(text, "instant", "", "", display_speaker_id)
    
    def _request_translate(self, text: str, request_type: str, context_prompt: str = "", last_text: str = "", speaker_id: Optional[int] = None) -> None:
        """
        请求翻译（事件驱动）
        
        Args:
            text: 待翻译文本
            request_type: "instant" 或 "full"
            context_prompt: 上下文提示词（仅完整翻译使用）
            last_text: 上一句话（仅完整翻译使用）
            speaker_id: 说话人ID（如果有多个说话人）
        """
        # 新的覆盖规则：
        # 1. 请求完整翻译时：
        #    - 如果当前pending_translate_request是完整翻译，则合并text到末尾（添加\n）
        #    - 如果当前pending_translate_request是即时翻译，则直接覆盖
        # 2. 请求即时翻译时：
        #    - 如果当前pending_translate_request是完整翻译，则抛弃即时翻译请求
        #    - 如果当前是即时翻译，则直接覆盖
        
        if request_type == "full":
            # 完整翻译请求
            if self.pending_translate_request and self.pending_translate_request["type"] == "full":
                # 如果当前是完整翻译，合并text到末尾（添加\n）
                existing_text = self.pending_translate_request.get("text", "")
                merged_text = existing_text + "\n" + text if existing_text else text
                # 合并时，使用最新的speaker_id（如果提供）
                self.pending_translate_request = {
                    "text": merged_text,
                    "type": "full",
                    "context_prompt": context_prompt,  # 使用新的context_prompt
                    "last_text": last_text,  # 使用新的last_text
                    "speaker_id": speaker_id if speaker_id is not None else self.pending_translate_request.get("speaker_id")
                }
            else:
                # 如果当前是即时翻译或没有请求，直接覆盖
                self.pending_translate_request = {
                    "text": text,
                    "type": "full",
                    "context_prompt": context_prompt,
                    "last_text": last_text,
                    "speaker_id": speaker_id
                }
        elif request_type == "instant":
            # 即时翻译请求
            if self.pending_translate_request and self.pending_translate_request["type"] == "full":
                # 如果当前是完整翻译，抛弃即时翻译请求
                return
            # 如果当前是即时翻译或没有请求，直接覆盖
            self.pending_translate_request = {
                "text": text,
                "type": "instant",
                "context_prompt": "",
                "last_text": "",
                "speaker_id": speaker_id
            }
        
        # 如果有待处理的请求且没有正在等待响应，通知工作线程
        if self.pending_translate_request and not self.is_waiting_for_response:
            self.translate_request_event.set()
    
    def _parse_translation_result(self, result: str) -> tuple[int, str]:
        """
        解析翻译结果，提取权重和翻译文本
        
        Args:
            result: AI模型返回的原始字符串
            
        Returns:
            tuple: (weight, translation_text)
                - weight: 权重值（100-199，其中100+ai_weight）
                - translation_text: 翻译结果文本
        """
        import json
        import re
        
        # 1. 先尝试JSON解码
        try:
            result_stripped = result.strip()
            # 移除可能的代码块标记（```json ... ```）
            # 匹配 ```json 或 ``` 开头和 ``` 结尾
            code_block_pattern = r'^```(?:json)?\s*?(.*?)\s*```\s*$'
            code_block_match = re.match(code_block_pattern, result_stripped, re.DOTALL)
            if code_block_match:
                # 提取代码块中的内容
                result_stripped = code_block_match.group(1).strip()
            
            # 处理特殊格式：json\n{"v":30,"t":"..."}
            # 匹配 json\n 开头的情况
            json_prefix_pattern = r'^json\s*(.*)$'
            json_prefix_match = re.match(json_prefix_pattern, result_stripped, re.DOTALL)
            if json_prefix_match:
                result_stripped = json_prefix_match.group(1).strip()
            
            # 尝试解析JSON
            parsed = json.loads(result_stripped)
            if isinstance(parsed, dict):
                # 提取翻译文本，优先使用 "t" 字段
                translation_text = None
                if "t" in parsed:
                    translation_text = parsed["t"]
                elif "text" in parsed:
                    translation_text = parsed["text"]
                elif "translation" in parsed:
                    translation_text = parsed["translation"]
                
                # 如果都没有找到，使用整个JSON字符串
                if translation_text is None:
                    translation_text = result_stripped
                else:
                    # 确保是字符串类型
                    translation_text = str(translation_text)
                
                # 提取权重值（可选）
                ai_weight = parsed.get("v", 0)
                if not isinstance(ai_weight, int) or ai_weight < 0 or ai_weight > 99:
                    ai_weight = 0
                
                weight = 100 + ai_weight  # 权重范围：100-199
                return weight, translation_text
        except (json.JSONDecodeError, ValueError, TypeError):
            # JSON解析失败，继续尝试其他方式
            pass
        
        # 2. 尝试使用|分隔符的解析方案
        weight_match = re.match(r'^(\d{1,2})\|', result.strip())
        if weight_match:
            ai_weight = int(weight_match.group(1))
            if 0 <= ai_weight <= 99:
                weight = 100 + ai_weight  # 权重范围：100-199
                # 移除权重前缀，只保留翻译结果
                translation_text = result[weight_match.end():].strip()
                return weight, translation_text
        
        # 3. 如果以上解析都不能完成，默认权重为0，将整个返回字符串作为翻译结果
        weight = 100  # 默认权重（100 + 0）
        translation_text = result.strip()
        return weight, translation_text
    
    def _translate_worker_loop(self) -> None:
        """常驻翻译工作线程的主循环"""
        import re
        import time
        import json
        import asyncio
        
        # 为这个线程创建持久的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            while not self.translate_thread_stop.is_set():
                # 等待翻译请求或停止信号（每0.1秒检查一次）
                if self.translate_request_event.wait(timeout=0.1):
                    # 有新的翻译请求
                    self.translate_request_event.clear()
                    
                    # 处理翻译请求
                    if self.pending_translate_request and self.is_translating:
                        request = self.pending_translate_request
                        self.pending_translate_request = None  # 清空等待中的请求
                        self.is_waiting_for_response = True
                        # 更新UI显示状态（使用信号确保线程安全）
                        self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
                        
                        
                        # 记录请求数据
                        request_data = {
                            "type": request["type"],
                            "text": request["text"],
                            "context_prompt": request.get("context_prompt", ""),
                            "last_text": request.get("last_text", "")
                        }
                        # print(f"准备请求翻译: {request_data}")
                        
                        try:
                            trans_config = self.config.get_translation_config()
                            use_ai = trans_config.get("use_ai_translation", True)
                            machine_config = trans_config.get("machine_translation", {})
                            
                            if request["type"] == "full":
                                # 完整翻译
                                if use_ai:
                                    # 检查API密钥
                                    if not self.translation_client or not self.translation_client.api_key:
                                        print("警告: API密钥未设置，无法翻译")
                                        self.is_waiting_for_response = False
                                        continue
                                    print(f'AI翻译上下文:{request["context_prompt"]}')
                                    # 使用AI翻译
                                    start_time = time.time()
                                    result = loop.run_until_complete(
                                        self.translation_client.translate_async(
                                            request["text"],
                                            request["context_prompt"],
                                            request["last_text"]
                                        )
                                    )
                                    total_time = time.time() - start_time
                                    # 记录耗时到统计列表
                                    self.translate_times.append(total_time)
                                    if len(self.translate_times) > 20:
                                        self.translate_times.pop(0)
                                    # 更新UI显示（使用信号确保线程安全）
                                    self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
                                    if result:
                                        # 解析翻译结果，提取权重和翻译文本
                                        weight, translation_text = self._parse_translation_result(result)
                                        
                                        # 将原文和权重保存到上下文管理器
                                        self.context_manager.add_context(request["text"], weight=weight)
                                        
                                        # 发送翻译结果到UI（传递说话人ID）
                                        request_speaker_id = request.get("speaker_id")
                                        self.window.translation_text_updated_signal.emit(translation_text, request_speaker_id)
                                    else:
                                        print(f"翻译失败: 返回结果为空")
                                        print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
                                        self.window.status_message_signal.emit("翻译失败: 返回结果为空", 5000)
                                else:
                                    # 使用机器翻译
                                    start_time = time.time()
                                    result, used_chars, error = loop.run_until_complete(
                                        self.translation_client.translate_tencent_async(
                                            request["text"],
                                            source_lang="auto",
                                            target_lang=machine_config.get("target_language", "zh"),
                                            secret_id=machine_config.get("tencent_secret_id", ""),
                                            secret_key=machine_config.get("tencent_secret_key", ""),
                                            region=machine_config.get("tencent_region", "ap-beijing"),
                                            project_id=machine_config.get("project_id", 0)
                                        )
                                    )
                                    total_time = time.time() - start_time
                                    # 记录耗时到统计列表
                                    self.translate_times.append(total_time)
                                    if len(self.translate_times) > 20:
                                        self.translate_times.pop(0)
                                    # 更新UI显示（使用信号确保线程安全）
                                    self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
                                    
                                    if error:
                                        print(f"机器翻译失败: {error}")
                                        self.window.status_message_signal.emit(f"机器翻译失败: {error}", 5000)
                                    elif result:
                                        # 更新字符数统计
                                        if used_chars:
                                            current_chars = machine_config.get("used_chars", 0)
                                            new_chars = current_chars + used_chars
                                            self.config.set("translation.machine_translation.used_chars", new_chars)
                                            self.config.save()
                                            # 更新UI显示
                                            self.window.update_used_chars_signal.emit(new_chars)
                                        
                                        # 机器翻译结果
                                        translation_text = result
                                        
                                        # 将原文和权重保存到上下文管理器（权重为100，默认权重）
                                        self.context_manager.add_context(request["text"], weight=100)
                                        
                                        # 发送翻译结果到UI（传递说话人ID）
                                        request_speaker_id = request.get("speaker_id")
                                        self.window.translation_text_updated_signal.emit(translation_text, request_speaker_id)
                                    else:
                                        print(f"机器翻译失败: 返回结果为空")
                                        self.window.status_message_signal.emit("机器翻译失败: 返回结果为空", 5000)
                            else:
                                # 即时翻译
                                instant_use_machine = trans_config.get("instant_use_machine_translation", True) if use_ai else True
                                
                                if instant_use_machine:
                                    # 使用机器翻译
                                    start_time = time.time()
                                    result, used_chars, error = loop.run_until_complete(
                                        self.translation_client.translate_tencent_async(
                                            request["text"],
                                            source_lang="auto",
                                            target_lang=machine_config.get("target_language", "zh"),
                                            secret_id=machine_config.get("tencent_secret_id", ""),
                                            secret_key=machine_config.get("tencent_secret_key", ""),
                                            region=machine_config.get("tencent_region", "ap-beijing"),
                                            project_id=machine_config.get("project_id", 0)
                                        )
                                    )
                                    total_time = time.time() - start_time
                                    # 记录耗时到统计列表
                                    self.translate_times.append(total_time)
                                    if len(self.translate_times) > 20:
                                        self.translate_times.pop(0)
                                    # 更新UI显示（使用信号确保线程安全）
                                    self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
                                    
                                    if error:
                                        print(f"即时机器翻译失败: {error}")
                                    elif result:
                                        # 更新字符数统计
                                        if used_chars:
                                            current_chars = machine_config.get("used_chars", 0)
                                            new_chars = current_chars + used_chars
                                            self.config.set("translation.machine_translation.used_chars", new_chars)
                                            self.config.save()
                                            # 更新UI显示
                                            self.window.update_used_chars_signal.emit(new_chars)
                                        
                                        # 即时翻译只更新最近一次翻译，不保存历史，不保存上下文（传递说话人ID）
                                        request_speaker_id = request.get("speaker_id")
                                        self.window.translation_latest_text_updated_signal.emit(result, request_speaker_id)
                                    else:
                                        print(f"即时机器翻译失败: 返回结果为空")
                                else:
                                    
                                    # 检查API密钥
                                    if not self.translation_client or not self.translation_client.api_key:
                                        print("警告: API密钥未设置，无法翻译")
                                        self.is_waiting_for_response = False
                                        continue
                                    # 使用AI翻译
                                    instant_prompt_template = trans_config.get("instant_prompt_template", "")
                                    
                                    if not instant_prompt_template:
                                        instant_prompt_template = trans_config.get("prompt_template", "")
                                    
                                    # 构建即时翻译提示词
                                    if instant_prompt_template:
                                        prompt = instant_prompt_template.replace("{text}", request["text"])
                                        prompt = prompt.replace("{context}", "当前新对话")
                                        prompt = prompt.replace("{last}", "")
                                    else:
                                        prompt = f"翻译以下文本为中文：{request['text']}"
                                    
                                    # 记录即时翻译的提示词
                                    request_data["prompt"] = prompt
                                    
                                    # 即时翻译 - 使用异步方法
                                    start_time = time.time()
                                    result = loop.run_until_complete(
                                        self.translation_client.translate_async_with_prompt(request["text"], prompt)
                                    )
                                    total_time = time.time() - start_time
                                    # 记录耗时到统计列表
                                    self.translate_times.append(total_time)
                                    if len(self.translate_times) > 20:
                                        self.translate_times.pop(0)
                                    # 更新UI显示（使用信号确保线程安全）
                                    self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
                                    
                                    if result:
                                        # 解析翻译结果，提取翻译文本（即时翻译不需要权重）
                                        _, translation_text = self._parse_translation_result(result)
                                        
                                        # 即时翻译只更新最近一次翻译，不保存历史，不保存上下文（传递说话人ID）
                                        request_speaker_id = request.get("speaker_id")
                                        self.window.translation_latest_text_updated_signal.emit(translation_text, request_speaker_id)
                                    else:
                                        print(f"即时翻译失败: 返回结果为空")
                                        print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
                        except Exception as e:
                            print(f"翻译错误: {e}")
                            print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
                            import traceback
                            traceback.print_exc()
                            if request["type"] == "full":
                                self.window.status_message_signal.emit(f"翻译失败: {e}", 5000)
                                self.context_manager.clear()
                        finally:
                            # 记录完成时间
                            self.last_translate_time = time.time()
                            # 标记不再等待响应
                            self.is_waiting_for_response = False
                            # 更新UI显示状态（使用信号确保线程安全）
                            self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
                            
                            # 如果还有下一个待处理的请求，立即处理（不需要等待轮询）
                            if self.pending_translate_request:
                                self.translate_request_event.set()
        finally:
            # 清理事件循环
            try:
                # 取消所有待处理的任务
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # 等待所有任务完成
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            finally:
                loop.close()
    
    
    def _on_device_changed(self, device_index: int) -> None:
        """设备改变回调（已废弃，保留兼容性）"""
        # 兼容旧代码，直接调用输入设备改变回调
        self._on_input_device_changed(device_index)
    
    def _on_input_device_changed(self, device_index: int) -> None:
        """输入设备改变回调（不立即重启监听）"""
        # 只保存配置，不立即重启监听
        self.config.set("audio.device_index", device_index)
        self.config.set("audio.device_type", "input")
        self.config.save()
        self.window.status_bar.showMessage("输入设备已选择，将在下次开启监听时生效", 2000)
    
    def _on_loopback_device_changed(self, device_index: int) -> None:
        """桌面音频设备改变回调（不立即重启监听）"""
        # 只保存配置，不立即重启监听
        self.config.set("audio.loopback_device_index", device_index)
        self.config.set("audio.device_type", "loopback")
        self.config.save()
        self.window.status_bar.showMessage("桌面音频设备已选择，将在下次开启监听时生效", 2000)
    
    def _on_device_type_changed(self, device_type: str) -> None:
        """设备类型改变回调（不立即重启监听）"""
        # 只保存配置，不立即重启监听
        self.config.set("audio.device_type", device_type)
        self.config.save()
        device_type_name = "输入设备" if device_type == "input" else "桌面音频"
        self.window.status_bar.showMessage(f"已切换到{device_type_name}，将在下次开启监听时生效", 2000)
    
    def _on_used_chars_updated(self, chars: int) -> None:
        """更新已消耗字符数"""
        if hasattr(self.window, '_update_used_chars_display'):
            self.window._update_used_chars_display(chars)
    
    def _on_volume_threshold_changed(self, threshold: float) -> None:
        """音量阈值改变回调（实时生效）"""
        # 保存配置
        self.config.set("audio.volume_threshold", threshold)
        self.config.save()
        
        # 实时更新当前捕获对象的音量阈值
        if self.audio_capture:
            self.audio_capture.volume_threshold = threshold
        if self.loopback_capture:
            self.loopback_capture.volume_threshold = threshold
        
        self.window.status_bar.showMessage(f"音量阈值已更新: {threshold}%", 2000)
    
    def _on_manual_translate(self, text: str) -> None:
        """手动翻译回调"""
        if not text or not text.strip():
            return
        
        # 检查API密钥
        trans_config = self.config.get_translation_config()
        if not trans_config.get("api_key"):
            self.window.show_error("配置错误", "请先设置API密钥")
            return
        
        # 模拟识别结果，更新识别文本显示
        self.window.update_recognition_text_for_test(text)
        
        # 获取上下文和上一句话
        context_prompt = self.context_manager.get_context()
        last_text = self.context_manager.get_last_text()
        
        # 使用统一的翻译请求方法
        self._request_translate(text, "full", context_prompt, last_text)
    
    
    def start_listening(self) -> None:
        """开启监听"""
        if self.is_listening:
            return
        
        try:
            audio_config = self.config.get_audio_config()
            device_type = audio_config.get("device_type", "input")
            device_index = audio_config.get("device_index")
            loopback_device_index = audio_config.get("loopback_device_index")
            process_interval_seconds = audio_config.get("process_interval_seconds", 3.0)
            volume_threshold = audio_config.get("volume_threshold", 1.0)
            sentence_break_interval = audio_config.get("sentence_break_interval", 2.0)
            
            # 根据设备类型创建或使用对应的捕获对象
            if device_type == "input":
                if device_index is None:
                    self.window.show_error("错误", "请先选择输入设备")
                    return
                
                # 如果捕获对象不存在或设备索引不匹配，重新创建
                if not self.audio_capture or self.audio_capture.device_index != device_index:
                    if self.audio_capture:
                        self.audio_capture.close()
                    self.audio_capture = AudioCapture(
                        sample_rate=audio_config.get("sample_rate", 16000),
                        channels=audio_config.get("channels", 1),
                        process_interval_seconds=process_interval_seconds,
                        format=audio_config.get("format", "int16"),
                        callback=self._on_audio_chunk,
                        volume_callback=self._on_volume_update,
                        device_index=device_index,
                        volume_threshold=volume_threshold,
                        sentence_break_interval=sentence_break_interval
                    )
                
                self.audio_capture.start()
            else:  # loopback
                if loopback_device_index is None:
                    self.window.show_error("错误", "请先选择桌面音频设备")
                    return
                
                # 如果捕获对象不存在或设备索引不匹配，重新创建
                if not self.loopback_capture or self.loopback_capture.device_index != loopback_device_index:
                    if self.loopback_capture:
                        self.loopback_capture.close()
                    self.loopback_capture = LoopbackAudioCapture(
                        sample_rate=audio_config.get("sample_rate", 16000),
                        channels=audio_config.get("channels", 1),
                        process_interval_seconds=process_interval_seconds,
                        format=audio_config.get("format", "int16"),
                        callback=self._on_audio_chunk,
                        volume_callback=self._on_volume_update,
                        device_index=loopback_device_index,
                        volume_threshold=volume_threshold,
                        sentence_break_interval=sentence_break_interval
                    )
                
                self.loopback_capture.start()
            
            self.is_listening = True
            self.window.set_listening_state(True)
            device_type_name = "输入设备" if device_type == "input" else "桌面音频"
            self.window.status_bar.showMessage(f"监听已开启 ({device_type_name})", 2000)
        except Exception as e:
            print(f"开启监听失败: {e}")
            self.window.show_error("错误", f"开启监听失败: {e}")
    
    def stop_listening(self) -> None:
        """关闭监听"""
        if not self.is_listening:
            return
        
        try:
            # 先关闭识别和翻译
            if self.is_recognizing:
                self.stop_recognition()
            if self.is_translating:
                self.stop_translation()
            
            if self.audio_capture:
                self.audio_capture.stop()
            if self.loopback_capture:
                self.loopback_capture.stop()
            
            self.is_listening = False
            self.window.set_listening_state(False)
            # 关闭监听后将音量显示归零
            self.window.update_volume(0.0)
            self.window.status_bar.showMessage("监听已关闭", 2000)
        except Exception as e:
            print(f"关闭监听失败: {e}")
    
    def load_model(self) -> None:
        """加载/重载语音识别模型"""
        try:
            # 获取当前选择的模型文件夹名称
            model_folder = self.window.language_combo.itemData(self.window.language_combo.currentIndex())
            if not model_folder:
                self.window.show_error("错误", "请先选择一个有效的模型")
                return
            
            vosk_config = self.config.get_vosk_config()
            model_path = vosk_config.get("model_path", "models")
            
            # 如果已有模型，先停止
            if self.vosk_engine:
                if self.is_recognizing:
                    self.vosk_engine.stop()
                self.vosk_engine = None
            
            # 加载新模型（使用模型文件夹名称作为language参数）
            audio_config = self.config.get_audio_config()
            self.vosk_engine = VoskEngine(
                model_path=model_path,
                language=model_folder,  # 直接使用模型文件夹名称
                sample_rate=audio_config.get("sample_rate", 16000),
                callback=self._on_recognition_result
            )
            
            # 检查模型是否加载成功
            if self.vosk_engine.model is None:
                self.window.set_model_loaded("")
                self.window.show_error("错误", f"未找到模型: {model_folder}")
                self.model_loaded = False
                return
            
            # 显示模型路径
            from pathlib import Path
            model_full_path = Path(model_path) / model_folder
            self.window.set_model_loaded(str(model_full_path))
            
            self.model_loaded = True
            self.window.status_bar.showMessage(f"模型加载成功: {model_folder}", 2000)
            
            # 重载模型后自动清空文本和上下文
            self._on_clear_texts()
            
            # 如果识别已开启，启动引擎
            if self.is_recognizing:
                self.vosk_engine.start()
        except Exception as e:
            print(f"加载模型失败: {e}")
            self.window.show_error("错误", f"加载模型失败: {e}")
            self.model_loaded = False
            self.window.set_model_loaded("")
    
    def _on_recognition_method_changed(self, method: int) -> None:
        """识别方式改变事件"""
        self.recognition_method = method
        # 保存识别方式到配置
        self.config.set("recognition.method", method)
        self.config.save()
        
        if method == 1:  # LiveCaptions
            # 选择Win11实时字幕，视为已开启监听并加载模型，启用开启识别按钮
            self.window.set_recognition_button_enabled(True)
        else:  # Vosk
            # 选择Vosk识别，需要检查监听和模型状态
            can_enable = self.is_listening and self.model_loaded
            self.window.set_recognition_button_enabled(can_enable)
    
    def _on_open_live_captions(self) -> None:
        """打开实时字幕"""
        try:
            # 检查LiveCaptions.exe进程是否存在
            process_found = False
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] and 'LiveCaptions.exe' in proc.info['name']:
                        process_found = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if not process_found:
                # 尝试启动LiveCaptions.exe
                live_captions_path = r"C:\Windows\System32\LiveCaptions.exe"
                if os.path.exists(live_captions_path):
                    try:
                        subprocess.Popen([live_captions_path], shell=False)
                        self.window.status_bar.showMessage("正在启动实时字幕...", 2000)
                    except Exception as e:
                        print(f"启动实时字幕失败: {e}")
                        self.window.show_error("错误", f"启动实时字幕失败: {e}")
                else:
                    self.window.show_error("错误", f"未找到实时字幕程序: {live_captions_path}")
            else:
                self.window.status_bar.showMessage("实时字幕已在运行", 2000)
        except Exception as e:
            print(f"打开实时字幕失败: {e}")
            self.window.show_error("错误", f"打开实时字幕失败: {e}")
    
    def start_recognition(self) -> None:
        """开启识别"""
        if self.is_recognizing:
            return
        
        if self.recognition_method == 0:  # Vosk识别
            if not self.is_listening:
                self.window.show_error("错误", "请先开启监听")
                return
            
            if not self.model_loaded or not self.vosk_engine:
                self.window.show_error("错误", "请先加载语音识别模型")
                return
            
            try:
                if self.vosk_engine:
                    self.vosk_engine.start()
                self.is_recognizing = True
                self.window.set_recognition_state(True)
                # 开启识别时只清空识别文本
                self.window.clear_recognition_text()
                self.window.status_bar.showMessage("识别已开启", 2000)
            except Exception as e:
                print(f"开启识别失败: {e}")
                self.window.show_error("错误", f"开启识别失败: {e}")
        else:  # LiveCaptions识别
            # 检查LiveCaptions.exe进程
            process_found = False
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] and 'LiveCaptions.exe' in proc.info['name']:
                        process_found = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if not process_found:
                # 尝试启动LiveCaptions.exe
                live_captions_path = r"C:\Windows\System32\LiveCaptions.exe"
                if os.path.exists(live_captions_path):
                    try:
                        subprocess.Popen([live_captions_path], shell=False)
                        # 等待一下让程序启动
                        import time
                        time.sleep(1)
                    except Exception as e:
                        print(f"启动实时字幕失败: {e}")
                        self.window.show_error("错误", f"启动实时字幕失败: {e}")
                        return
                else:
                    self.window.show_error("错误", f"未找到实时字幕程序: {live_captions_path}")
                    return
            
            # 初始化LiveCaptions引擎
            if not self.live_captions_engine:
                self.live_captions_engine = LiveCaptionsEngine(callback=self._on_recognition_result)
            
            # 启动字幕监听
            if self.live_captions_engine.start():
                self.is_recognizing = True
                self.window.set_recognition_state(True)
                # 开启识别时只清空识别文本
                self.window.clear_recognition_text()
                self.window.status_bar.showMessage("实时字幕识别已开启", 2000)
            else:
                self.window.show_error("错误", "启动实时字幕监听失败，请确保已开启Windows 11实时字幕")
    
    def stop_recognition(self) -> None:
        """关闭识别"""
        if not self.is_recognizing:
            return
        
        try:
            # 先关闭翻译
            if self.is_translating:
                self.stop_translation()
            
            if self.recognition_method == 0:  # Vosk识别
                if self.vosk_engine:
                    self.vosk_engine.stop()
            else:  # LiveCaptions识别
                if self.live_captions_engine:
                    self.live_captions_engine.stop()
            
            self.is_recognizing = False
            self.window.set_recognition_state(False)
            # 关闭识别时不清空识别文本
            self.window.status_bar.showMessage("识别已关闭", 2000)
        except Exception as e:
            print(f"关闭识别失败: {e}")
    
    def _check_translation_config(self) -> tuple[bool, str]:
        """
        检查翻译配置是否完整
        
        Returns:
            (是否配置完整, 错误信息)
        """
        trans_config = self.config.get_translation_config()
        use_ai = trans_config.get("use_ai_translation", True)
        machine_config = trans_config.get("machine_translation", {})
        
        if use_ai:
            # 使用AI翻译，需要检查大模型API密钥
            if not self.translation_client or not self.translation_client.api_key:
                return False, "AI翻译需要设置API密钥"
            
            # 检查是否启用即时翻译使用机翻
            instant_use_machine = trans_config.get("instant_use_machine_translation", True)
            if instant_use_machine:
                # 即时翻译使用机翻，需要检查机翻配置
                if not machine_config.get("tencent_secret_id") or not machine_config.get("tencent_secret_key"):
                    return False, "即时翻译使用机翻需要设置腾讯云SecretId和SecretKey"
        else:
            # 不使用AI翻译，完整翻译和即时翻译都用机翻
            if not machine_config.get("tencent_secret_id") or not machine_config.get("tencent_secret_key"):
                return False, "机器翻译需要设置腾讯云SecretId和SecretKey"
        
        return True, ""
    
    def start_translation(self) -> None:
        """开启翻译"""
        if self.is_translating:
            return
        
        if not self.is_recognizing:
            self.window.show_error("错误", "请先开启识别")
            return
        
        # 检查翻译配置
        config_ok, error_msg = self._check_translation_config()
        if not config_ok:
            self.window.show_error("配置错误", error_msg)
            return
        
        try:
            self.context_manager.clear()
            # 初始化翻译状态
            self.pending_translate_request = None
            self.is_waiting_for_response = False
            self.last_translate_time = 0.0
            self.is_translating = True
            
            # 启动常驻翻译线程（如果还没有启动）
            if not self.translate_thread_running:
                self.translate_thread_stop.clear()
                self.translate_thread_running = True
                self.translate_thread = threading.Thread(target=self._translate_worker_loop, daemon=True)
                self.translate_thread.start()
            
            self.window.set_translation_state(True)
            # 开启翻译时只清空翻译文本框和上下文缓存
            self.window.clear_translation_texts()
            # 更新状态显示（使用信号确保线程安全）
            self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
            self.window.status_bar.showMessage("翻译已开启", 2000)
        except Exception as e:
            print(f"开启翻译失败: {e}")
            self.window.show_error("错误", f"开启翻译失败: {e}")
    
    def stop_translation(self) -> None:
        """关闭翻译"""
        if not self.is_translating:
            return
        
        try:
            # 清空等待中的请求
            self.pending_translate_request = None
            self.is_translating = False
            self.is_waiting_for_response = False
            # 注意：不停止常驻线程，让它继续运行等待下次开启翻译
            self.window.set_translation_state(False)
            # 更新状态显示（使用信号确保线程安全）
            self.window.translation_status_updated_signal.emit(self.is_translating, self.is_waiting_for_response, self.translate_times.copy())
            # 关闭翻译时不清空任何文本框
            self.window.status_bar.showMessage("翻译已关闭", 2000)
        except Exception as e:
            print(f"关闭翻译失败: {e}")
    
    def _refresh_devices(self) -> None:
        """刷新设备列表"""
        try:
            audio_config = self.config.get_audio_config()
            process_interval_seconds = audio_config.get("process_interval_seconds", 3.0)
            sentence_break_interval = audio_config.get("sentence_break_interval", 2.0)
            
            # 获取输入设备列表
            input_devices = []
            try:
                if self.audio_capture and isinstance(self.audio_capture, AudioCapture):
                    input_devices = self.audio_capture.get_available_devices()
                else:
                    temp_capture = AudioCapture(
                        sample_rate=audio_config.get("sample_rate", 16000),
                        channels=audio_config.get("channels", 1),
                        process_interval_seconds=process_interval_seconds,
                        format=audio_config.get("format", "int16"),
                        device_index=None,  # 不初始化设备，只用于获取列表
                        sentence_break_interval=sentence_break_interval
                    )
                    input_devices = temp_capture.get_available_devices()
                    temp_capture.close()
            except Exception as e:
                print(f"获取输入设备列表失败: {e}")
            
            # 获取桌面音频设备列表
            loopback_devices = []
            try:
                if self.audio_capture and isinstance(self.audio_capture, LoopbackAudioCapture):
                    loopback_devices = self.audio_capture.get_available_devices()
                else:
                    temp_loopback = LoopbackAudioCapture(
                        sample_rate=audio_config.get("sample_rate", 16000),
                        channels=audio_config.get("channels", 1),
                        process_interval_seconds=process_interval_seconds,
                        format=audio_config.get("format", "int16"),
                        device_index=None,
                        sentence_break_interval=sentence_break_interval
                    )
                    loopback_devices = temp_loopback.get_available_devices()
                    temp_loopback.close()
            except Exception as e:
                print(f"获取桌面音频设备列表失败: {e}")
            
            # 更新GUI设备列表
            device_type = audio_config.get("device_type", "input")
            default_input_index = audio_config.get("device_index")
            default_loopback_index = audio_config.get("loopback_device_index")
            self.window.update_device_list(
                input_devices,
                loopback_devices,
                default_input_index=default_input_index,
                default_loopback_index=default_loopback_index,
                device_type=device_type
            )
        except Exception as e:
            print(f"刷新设备列表失败: {e}")
            self.window.show_error("错误", f"刷新设备列表失败: {e}")
    
    def _on_clear_texts(self) -> None:
        """清空所有文本和上下文"""
        # 清空UI文本
        self.window.clear_all_texts()
        # 清空上下文缓存
        self.context_manager.clear()
        print("已清空所有文本和上下文缓存")
    
    def _on_instant_translate_changed(self, enabled: bool) -> None:
        """即时翻译设置改变回调"""
        # 配置已经在UI中更新并保存，这里只需要确认
        # _on_recognition_result 方法会从 config 实时读取，所以这里不需要额外操作
        print(f"即时翻译设置已更新: {'启用' if enabled else '禁用'}")
    
    def _on_apply_settings(self) -> None:
        """应用设置（保存设置到配置文件）"""
        try:
            # 保存音频设置
            # 注意：采样率和声道数是只读的，用于Vosk引擎，不需要从UI保存
            # if hasattr(self.window, 'audio_sample_rate_spin'):
            #     self.config.set("audio.sample_rate", self.window.audio_sample_rate_spin.value())
            # if hasattr(self.window, 'audio_channels_spin'):
            #     self.config.set("audio.channels", self.window.audio_channels_spin.value())
            if hasattr(self.window, 'audio_process_interval_spin'):
                self.config.set("audio.process_interval_seconds", self.window.audio_process_interval_spin.value())
            if hasattr(self.window, 'audio_sentence_break_interval_spin'):
                self.config.set("audio.sentence_break_interval", self.window.audio_sentence_break_interval_spin.value())
            if hasattr(self.window, 'audio_format_combo'):
                self.config.set("audio.format", self.window.audio_format_combo.currentText())
            
            # 保存Vosk设置
            if hasattr(self.window, 'vosk_model_path_edit'):
                self.config.set("vosk.model_path", self.window.vosk_model_path_edit.text())
            
            # 保存翻译设置
            if hasattr(self.window, 'trans_provider_combo'):
                self.config.set("translation.api_provider", self.window.trans_provider_combo.currentText())
            if hasattr(self.window, 'trans_api_key_edit'):
                self.config.set("translation.api_key", self.window.trans_api_key_edit.text())
            if hasattr(self.window, 'trans_api_url_edit'):
                self.config.set("translation.api_url", self.window.trans_api_url_edit.text())
            if hasattr(self.window, 'trans_model_edit'):
                self.config.set("translation.model", self.window.trans_model_edit.text())
            if hasattr(self.window, 'trans_timeout_spin'):
                self.config.set("translation.timeout", self.window.trans_timeout_spin.value())
            if hasattr(self.window, 'trans_max_tokens_spin'):
                self.config.set("translation.max_tokens", self.window.trans_max_tokens_spin.value())
            if hasattr(self.window, 'trans_temperature_spin'):
                self.config.set("translation.temperature", self.window.trans_temperature_spin.value())
            
            # 保存记忆设置
            if hasattr(self.window, 'trans_memory_count_spin'):
                self.config.set("translation.memory_max_count", self.window.trans_memory_count_spin.value())
            if hasattr(self.window, 'trans_memory_time_spin'):
                self.config.set("translation.memory_time", self.window.trans_memory_time_spin.value())
            
            # 保存提示词设置
            if hasattr(self.window, 'prompt_template_edit'):
                self.config.set("translation.prompt_template", self.window.prompt_template_edit.toPlainText())
            if hasattr(self.window, 'instant_prompt_template_edit'):
                self.config.set("translation.instant_prompt_template", self.window.instant_prompt_template_edit.toPlainText())
            
            # 保存即时翻译设置
            if hasattr(self.window, 'instant_translate_checkbox'):
                self.config.set("translation.instant_translate", self.window.instant_translate_checkbox.isChecked())
            if hasattr(self.window, 'instant_translate_interval_spin'):
                self.config.set("translation.instant_translate_interval", self.window.instant_translate_interval_spin.value())
            if hasattr(self.window, 'instant_translate_trigger_chars_spin'):
                self.config.set("translation.instant_translate_trigger_chars", self.window.instant_translate_trigger_chars_spin.value())
            
            # 保存机器翻译设置
            if hasattr(self.window, 'tencent_secret_id_edit'):
                self.config.set("translation.machine_translation.tencent_secret_id", self.window.tencent_secret_id_edit.text())
            if hasattr(self.window, 'tencent_secret_key_edit'):
                self.config.set("translation.machine_translation.tencent_secret_key", self.window.tencent_secret_key_edit.text())
            if hasattr(self.window, 'tencent_region_combo'):
                region_value = self.window.tencent_region_combo.currentData()
                if region_value:
                    self.config.set("translation.machine_translation.tencent_region", region_value)
            if hasattr(self.window, 'tencent_target_lang_combo'):
                self.config.set("translation.machine_translation.target_language", self.window.tencent_target_lang_combo.currentText())
            if hasattr(self.window, 'tencent_project_id_spin'):
                self.config.set("translation.machine_translation.project_id", self.window.tencent_project_id_spin.value())
            # 注意：used_chars 不需要从UI保存，它由程序运行时自动更新
            
            # 保存配置
            self.config.save()
            
            # 更新翻译客户端配置（如果已初始化）
            if self.translation_client:
                trans_config = self.config.get_translation_config()
                self.translation_client.update_config(
                    api_key=self.config.get("translation.api_key", ""),
                    api_url=self.config.get("translation.api_url", ""),
                    model=self.config.get("translation.model", "deepseek-chat"),
                    trans_config=trans_config  # 传递配置以便更新提示词模板
                )
            
            # 更新上下文管理器配置
            trans_config = self.config.get_translation_config()
            self.context_manager.update_config(
                max_count=trans_config.get("memory_max_count", 10),
                memory_time=trans_config.get("memory_time", 300.0)
            )
            
            self.window.status_message_signal.emit("设置已保存", 2000)
            print("设置已保存到配置文件")
            
        except Exception as e:
            print(f"保存设置失败: {e}")
            self.window.show_error("错误", f"保存设置失败: {e}")
    
    def _update_context_info_tooltip(self) -> None:
        """更新上下文信息tooltip"""
        try:
            context_detail = self.context_manager.get_context_detail()
            self.window.update_context_info_tooltip(context_detail)
        except Exception as e:
            print(f"更新上下文信息tooltip失败: {e}")
    
    def run(self) -> int:
        """运行应用"""
        self.window.show()
        return self.app.exec()
    
    def cleanup(self) -> None:
        """清理资源"""
        # 停止上下文信息更新定时器
        if hasattr(self, 'context_info_timer'):
            self.context_info_timer.stop()
        
        # 关闭所有功能
        if self.is_translating:
            self.stop_translation()
        if self.is_recognizing:
            self.stop_recognition()
        if self.is_listening:
            self.stop_listening()
        
        # 停止常驻翻译线程
        if self.translate_thread_running:
            self.translate_thread_stop.set()
            self.translate_request_event.set()  # 唤醒线程以便它检查停止信号
            if self.translate_thread and self.translate_thread.is_alive():
                print("等待翻译线程结束...")
                self.translate_thread.join(timeout=3.0)
                if self.translate_thread.is_alive():
                    print("警告: 翻译线程未在超时时间内完成")
            self.translate_thread_running = False
        
        if self.audio_capture:
            self.audio_capture.close()
        if self.translation_client:
            self.translation_client.close()

def main():
    """主函数"""
    app = None
    try:
        app = TranslatorApp()
        exit_code = app.run()
        return exit_code
    except KeyboardInterrupt:
        print("\n程序被用户中断")
        return 0
    except Exception as e:
        print(f"程序运行错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if app:
            app.cleanup()

if __name__ == "__main__":
    sys.exit(main())
