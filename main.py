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
from src.recognition.vosk_engine import VoskEngine
from src.translation.api_client import TranslationClient
from src.translation.context_manager import WeightedContextManager
from src.ui.main_window import MainWindow

class TranslatorApp:
    """翻译器应用主类"""
    
    def __init__(self):
        """初始化应用"""
        self.config = Config()
        
        # 初始化各个模块
        self.audio_capture: Optional[AudioCapture] = None
        self.vosk_engine: Optional[VoskEngine] = None
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
        
        # 翻译请求状态管理（事件驱动模式）
        self.pending_translate_request: Optional[dict] = None  # 等待中的请求：{"text": str, "type": "instant"/"full", "context_prompt": str, "last_text": str}
        self.is_waiting_for_response = False  # 是否正在等待上一个请求返回
        self.last_translate_time = 0.0  # 上次翻译完成时间
        self.translate_thread: Optional[threading.Thread] = None  # 单个翻译工作线程
        
        # 创建GUI
        self.app = QApplication(sys.argv)
        self.window = MainWindow(self.config)
        
        # 连接信号
        self._connect_signals()
        
        # 初始化模块
        self._init_modules()
        
        # 不再检查VR状态
    
    def _connect_signals(self) -> None:
        """连接信号和槽"""
        self.window.listen_start_signal.connect(self.start_listening)
        self.window.listen_stop_signal.connect(self.stop_listening)
        self.window.load_model_signal.connect(self.load_model)
        self.window.recognition_start_signal.connect(self.start_recognition)
        self.window.recognition_stop_signal.connect(self.stop_recognition)
        self.window.translation_start_signal.connect(self.start_translation)
        self.window.translation_stop_signal.connect(self.stop_translation)
        # 不再需要language_changed_signal，UI自己处理
        self.window.device_changed_signal.connect(self._on_device_changed)
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
    
    def _init_modules(self) -> None:
        """初始化各个模块"""
        try:
            # 初始化音频捕获
            audio_config = self.config.get_audio_config()
            device_index = audio_config.get("device_index")
            
            # 先创建临时AudioCapture对象以获取设备列表（不启动流）
            try:
                # 创建临时对象获取设备列表
                temp_capture = AudioCapture(
                    sample_rate=audio_config.get("sample_rate", 16000),
                    channels=audio_config.get("channels", 1),
                    chunk_size=audio_config.get("chunk_size", 1024),
                    format=audio_config.get("format", "int16"),
                    device_index=None  # 不指定设备，只用于获取列表
                )
                # 获取设备列表并更新GUI
                devices = temp_capture.get_available_devices()
                self.window.update_device_list(devices, device_index)
                temp_capture.close()
            except Exception as e:
                print(f"获取设备列表失败: {e}")
                # 继续初始化，使用默认设备
            
            # 创建实际的音频捕获对象
            self.audio_capture = AudioCapture(
                sample_rate=audio_config.get("sample_rate", 16000),
                channels=audio_config.get("channels", 1),
                chunk_size=audio_config.get("chunk_size", 1024),
                format=audio_config.get("format", "int16"),
                callback=self._on_audio_chunk,  # 改为处理累积的音频块
                volume_callback=self._on_volume_update,  # 音量更新回调
                device_index=device_index
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
    
    def _on_recognition_result(self, text: str, is_final: bool) -> None:
        """识别结果回调（可能在非主线程中调用）"""
        if not text or not text.strip():
            return
        
        # 获取当前模型文件夹名称，检查是否是英语模型
        vosk_config = self.config.get_vosk_config()
        current_model = vosk_config.get("language", "")
        
        # 过滤英语模型的无效识别结果 'the'
        # 检查模型文件夹名称是否包含英语相关关键词
        if current_model and ("en" in current_model.lower() or "english" in current_model.lower()):
            text_stripped = text.strip().lower()
            if text_stripped == "the":
                return  # 忽略无效的 'the' 识别结果
        
        # 直接使用信号emit（信号是线程安全的）
        self.window.recognition_text_updated_signal.emit(text, is_final)
        
        if self.is_translating:
            if is_final:
                # 完整句子翻译
                self.current_text = text
                context_prompt = self.context_manager.get_context()
                last_text = self.context_manager.get_last_text()
                self._request_translate(text, "full", context_prompt, last_text)
            else:
                # 部分结果：检查是否启用即时翻译
                trans_config = self.config.get_translation_config()
                instant_translate_enabled = trans_config.get("instant_translate", False)
                if instant_translate_enabled:
                    text_utf8_len = len(text.encode('utf-8'))
                    if text_utf8_len > 8:
                        # 即时翻译请求
                        self._request_translate(text, "instant", "", "")
    
    def _request_translate(self, text: str, request_type: str, context_prompt: str = "", last_text: str = "") -> None:
        """
        请求翻译（事件驱动）
        
        Args:
            text: 待翻译文本
            request_type: "instant" 或 "full"
            context_prompt: 上下文提示词（仅完整翻译使用）
            last_text: 上一句话（仅完整翻译使用）
        """
        # 覆盖规则：
        # 1. 完整翻译可以覆盖等待中的即时翻译
        # 2. 即时翻译不能覆盖等待中的完整翻译
        # 3. 后一个即时翻译可以覆盖前一个尚未进行请求的即时翻译
        
        if request_type == "full":
            # 完整翻译：可以覆盖任何等待中的请求
            self.pending_translate_request = {
                "text": text,
                "type": "full",
                "context_prompt": context_prompt,
                "last_text": last_text
            }
        elif request_type == "instant":
            # 即时翻译：
            # - 如果正在等待响应，不能覆盖
            # - 如果等待中的是完整翻译，不能覆盖
            # - 如果等待中的是即时翻译，可以覆盖
            if self.is_waiting_for_response:
                # 正在等待响应，不能覆盖
                return
            if self.pending_translate_request and self.pending_translate_request["type"] == "full":
                # 等待中的是完整翻译，不能覆盖
                return
            # 可以覆盖（包括空请求和即时翻译请求）
            self.pending_translate_request = {
                "text": text,
                "type": "instant",
                "context_prompt": "",
                "last_text": ""
            }
        
        # 如果当前没有等待响应，立即处理请求
        if not self.is_waiting_for_response:
            self._process_translate_request()
    
    def _process_translate_request(self) -> None:
        """处理等待中的翻译请求"""
        if not self.pending_translate_request:
            return
        
        if not self.translation_client or not self.translation_client.api_key:
            print("警告: API密钥未设置，无法翻译")
            self.pending_translate_request = None
            return
        
        # 获取请求信息
        request = self.pending_translate_request
        self.pending_translate_request = None  # 清空等待中的请求
        self.is_waiting_for_response = True  # 标记为正在等待响应
        
        # 在新线程中执行翻译
        def translate_worker():
            import re
            import time
            import json
            
            # 记录请求数据
            request_data = {
                "type": request["type"],
                "text": request["text"],
                "context_prompt": request.get("context_prompt", ""),
                "last_text": request.get("last_text", "")
            }
            
            try:
                if request["type"] == "full":
                    # 完整翻译
                    result = self.translation_client.translate(
                        request["text"],
                        request["context_prompt"],
                        request["last_text"]
                    )
                    if result:
                        # 解析翻译结果，提取权重
                        weight = 100  # 默认权重
                        translation_text = result
                        
                        # 尝试匹配开头的权重格式：数字+|分隔符
                        weight_match = re.match(r'^(\d{1,2})\|', result.strip())
                        if weight_match:
                            ai_weight = int(weight_match.group(1))
                            if 0 <= ai_weight <= 99:
                                weight = 100 + ai_weight  # 权重范围：100-199
                                # 移除权重前缀，只保留翻译结果
                                translation_text = result[weight_match.end():].strip()
                        
                        # 将原文和权重保存到上下文管理器
                        self.context_manager.add_context(request["text"], weight=weight)
                        
                        # 发送翻译结果到UI
                        self.window.translation_text_updated_signal.emit(translation_text)
                    else:
                        print(f"翻译失败: 返回结果为空")
                        print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
                        self.window.status_message_signal.emit("翻译失败: 返回结果为空", 5000)
                else:
                    # 即时翻译
                    trans_config = self.config.get_translation_config()
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
                    
                    result = self.translation_client.translate_with_prompt(request["text"], prompt)
                    
                    if result:
                        # 移除权重前缀（如果有）
                        translation_text = result
                        weight_match = re.match(r'^(\d{1,2})\|', result.strip())
                        if weight_match:
                            translation_text = result[weight_match.end():].strip()
                        
                        # 即时翻译只更新最近一次翻译，不保存历史，不保存上下文
                        self.window.translation_latest_text_updated_signal.emit(translation_text)
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
                # 处理下一个等待中的请求（如果有）
                if self.pending_translate_request:
                    self._process_translate_request()
        
        # 启动翻译线程（应该总是创建新线程，因为is_waiting_for_response已经阻止了并发）
        # 但在创建新线程之前，先等待旧线程完成（如果存在且仍在运行）
        if self.translate_thread and self.translate_thread.is_alive():
            # 等待旧线程完成，但设置超时避免无限等待
            self.translate_thread.join(timeout=0.1)
        
        self.translate_thread = threading.Thread(target=translate_worker, daemon=True)
        self.translate_thread.start()
    
    
    def _on_device_changed(self, device_index: int) -> None:
        """设备改变回调"""
        # 保存旧设备索引（用于错误恢复）
        old_device_index = self.config.get("audio.device_index")
        
        # 保存设备选择到配置
        self.config.set("audio.device_index", device_index)
        self.config.save()
        
        # 记录当前状态
        was_listening = self.is_listening
        was_recognizing = self.is_recognizing
        was_translating = self.is_translating
        
        try:
            # 如果正在监听，先停止
            if self.is_listening:
                # 先关闭识别和翻译（如果正在运行）
                if self.is_recognizing:
                    self.stop_recognition()
                if self.is_translating:
                    self.stop_translation()
                
                # 停止音频捕获
                if self.audio_capture:
                    self.audio_capture.stop()
                    self.audio_capture.close()
                    self.audio_capture = None
                self.is_listening = False
                # 停止音频捕获后将音量显示归零
                self.window.update_volume(0.0)
            
            # 重新创建音频捕获对象（使用新的设备索引）
            audio_config = self.config.get_audio_config()
            self.audio_capture = AudioCapture(
                sample_rate=audio_config.get("sample_rate", 16000),
                channels=audio_config.get("channels", 1),
                chunk_size=audio_config.get("chunk_size", 1024),
                format=audio_config.get("format", "int16"),
                callback=self._on_audio_chunk,
                volume_callback=self._on_volume_update,
                device_index=device_index
            )
            
            # 如果之前正在监听，重新启动监听
            if was_listening:
                self.audio_capture.start()
                self.is_listening = True
                self.window.set_listening_state(True)
                
                # 如果之前正在识别，重新启动识别
                if was_recognizing and self.vosk_engine:
                    self.vosk_engine.start()
                    self.is_recognizing = True
                    self.window.set_recognition_state(True)
                
                # 如果之前正在翻译，重新启动翻译
                if was_translating:
                    self.context_manager.clear()
                    self.pending_translate_request = None
                    self.is_waiting_for_response = False
                    self.last_translate_time = 0.0
                    self.is_translating = True
                    self.window.set_translation_state(True)
                
                self.window.status_bar.showMessage("设备已切换，监听已重启", 2000)
            else:
                self.window.status_bar.showMessage("设备已切换", 2000)
                
        except Exception as e:
            print(f"切换设备失败: {e}")
            self.window.show_error("错误", f"切换设备失败: {e}")
            # 如果切换失败，回滚配置并尝试恢复到之前的状态
            if old_device_index is not None:
                self.config.set("audio.device_index", old_device_index)
                self.config.save()
                # 更新UI中的设备选择（需要创建临时对象获取设备列表）
                try:
                    audio_config = self.config.get_audio_config()
                    temp_capture = AudioCapture(
                        sample_rate=audio_config.get("sample_rate", 16000),
                        channels=audio_config.get("channels", 1),
                        chunk_size=audio_config.get("chunk_size", 1024),
                        format=audio_config.get("format", "int16"),
                        device_index=None
                    )
                    devices = temp_capture.get_available_devices()
                    temp_capture.close()
                    self.window.update_device_list(devices, old_device_index)
                except:
                    pass
            
            if was_listening:
                try:
                    # 尝试使用旧的设备索引重新创建
                    if old_device_index is not None:
                        audio_config = self.config.get_audio_config()
                        self.audio_capture = AudioCapture(
                            sample_rate=audio_config.get("sample_rate", 16000),
                            channels=audio_config.get("channels", 1),
                            chunk_size=audio_config.get("chunk_size", 1024),
                            format=audio_config.get("format", "int16"),
                            callback=self._on_audio_chunk,
                            volume_callback=self._on_volume_update,
                            device_index=old_device_index
                        )
                        self.audio_capture.start()
                        self.is_listening = True
                        self.window.set_listening_state(True)
                except Exception as restore_error:
                    print(f"恢复旧设备失败: {restore_error}")
                    self.is_listening = False
                    self.window.set_listening_state(False)
    
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
            if self.audio_capture:
                self.audio_capture.start()
            self.is_listening = True
            self.window.set_listening_state(True)
            self.window.status_bar.showMessage("监听已开启", 2000)
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
    
    def start_recognition(self) -> None:
        """开启识别"""
        if self.is_recognizing:
            return
        
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
    
    def stop_recognition(self) -> None:
        """关闭识别"""
        if not self.is_recognizing:
            return
        
        try:
            # 先关闭翻译
            if self.is_translating:
                self.stop_translation()
            
            if self.vosk_engine:
                self.vosk_engine.stop()
            self.is_recognizing = False
            self.window.set_recognition_state(False)
            # 关闭识别时不清空识别文本
            self.window.status_bar.showMessage("识别已关闭", 2000)
        except Exception as e:
            print(f"关闭识别失败: {e}")
    
    def start_translation(self) -> None:
        """开启翻译"""
        if self.is_translating:
            return
        
        if not self.is_recognizing:
            self.window.show_error("错误", "请先开启识别")
            return
        
        # 检查API密钥
        trans_config = self.config.get_translation_config()
        if not trans_config.get("api_key"):
            self.window.show_error("配置错误", "请先设置API密钥")
            return
        
        try:
            self.context_manager.clear()
            # 初始化翻译状态
            self.pending_translate_request = None
            self.is_waiting_for_response = False
            self.last_translate_time = 0.0
            self.is_translating = True
            self.window.set_translation_state(True)
            # 开启翻译时只清空翻译文本框和上下文缓存
            self.window.clear_translation_texts()
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
            # 等待当前翻译完成（最多等待2秒）
            if self.translate_thread and self.translate_thread.is_alive():
                self.translate_thread.join(timeout=2.0)
                # 如果线程仍在运行，说明超时了，但daemon线程会在主程序退出时自动终止
                if self.translate_thread.is_alive():
                    print("警告: 翻译线程未在超时时间内完成，但daemon线程会在程序退出时自动终止")
            
            self.is_translating = False
            self.is_waiting_for_response = False
            self.translate_thread = None  # 清空线程引用
            self.window.set_translation_state(False)
            # 关闭翻译时不清空任何文本框
            self.window.status_bar.showMessage("翻译已关闭", 2000)
        except Exception as e:
            print(f"关闭翻译失败: {e}")
    
    def _refresh_devices(self) -> None:
        """刷新设备列表"""
        try:
            if self.audio_capture:
                devices = self.audio_capture.get_available_devices()
                current_device = self.config.get("audio.device_index")
                self.window.update_device_list(devices, current_device)
            else:
                # 如果音频捕获未初始化，创建临时对象获取设备列表
                audio_config = self.config.get_audio_config()
                temp_capture = AudioCapture(
                    sample_rate=audio_config.get("sample_rate", 16000),
                    channels=audio_config.get("channels", 1),
                    chunk_size=audio_config.get("chunk_size", 1024),
                    format=audio_config.get("format", "int16"),
                    device_index=None  # 不初始化设备，只获取列表
                )
                devices = temp_capture.get_available_devices()
                current_device = self.config.get("audio.device_index")
                self.window.update_device_list(devices, current_device)
                temp_capture.close()
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
            if hasattr(self.window, 'audio_chunk_size_spin'):
                self.config.set("audio.chunk_size", self.window.audio_chunk_size_spin.value())
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
    
    def run(self) -> int:
        """运行应用"""
        self.window.show()
        return self.app.exec()
    
    def cleanup(self) -> None:
        """清理资源"""
        # 关闭所有功能
        if self.is_translating:
            self.stop_translation()
        if self.is_recognizing:
            self.stop_recognition()
        if self.is_listening:
            self.stop_listening()
        
        # 确保所有翻译线程都已结束
        if self.translate_thread and self.translate_thread.is_alive():
            print("等待翻译线程结束...")
            self.translate_thread.join(timeout=3.0)
            if self.translate_thread.is_alive():
                print("警告: 翻译线程未在超时时间内完成")
        
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
