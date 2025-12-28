"""VR翻译器主程序优化版"""
from typing import Optional, Tuple
from pathlib import Path
import sys
import threading
import ctypes
from PyQt6.QtWidgets import QApplication
from config import Config
from src.audio.capture_cable import AudioCapture
from src.audio.capture_loopback import LoopbackAudioCapture
from src.recognition.vosk_engine import VoskEngine
from src.translation.api_client import TranslationClient
from src.translation.context_manager import WeightedContextManager
from src.ui.main_window import MainWindow

class TranslatorApp:
    """翻译器应用主类（优化版）"""

    def __init__(self):
        """
        初始化应用实例
        初始化顺序: 状态变量 -> GUI -> 信号连接 -> 模块初始化
        """
        self.config = Config()
        self._init_state_variables()
        self._init_gui()
        self._connect_signals()
        self._init_modules()

    def _init_state_variables(self) -> None:
        """
        初始化状态变量和上下文管理器
        包括: 模块实例、状态标志、翻译线程变量等
        """
        # 模块实例
        self.audio_capture: Optional[AudioCapture] = None
        self.loopback_capture: Optional[LoopbackAudioCapture] = None
        self.vosk_engine: Optional[VoskEngine] = None
        self.translation_client: Optional[TranslationClient] = None

        # 上下文管理器配置
        trans_config = self.config.get_translation_config()
        self.context_manager = WeightedContextManager(
            max_count=trans_config.get("memory_max_count", 10),
            memory_time=trans_config.get("memory_time", 300.0)
        )

        # 状态标志
        """可能出现非法状态组合导致不可预测错误，有空修为枚举添加状态机"""
        self.is_listening = False
        self.is_recognizing = False
        self.is_translating = False
        self.model_loaded = False
        self.current_text = ""

        # 翻译线程管理变量
        self._init_translation_thread_vars()

    def _init_translation_thread_vars(self) -> None:
        """
        初始化翻译线程相关变量
        包括: 待处理请求、线程控制事件等
        """
        self.pending_translate_request: Optional[dict] = None
        self.is_waiting_for_response = False
        self.last_translate_time = 0.0
        self.translate_thread: Optional[threading.Thread] = None
        self.translate_thread_stop = threading.Event()
        self.translate_request_event = threading.Event()
        self.translate_thread_running = False
        self.translate_times = []

    def _init_gui(self) -> None:
        """
        初始化GUI界面
        包括: 创建QApplication、应用暗色主题、创建主窗口
        """
        self.app = QApplication(sys.argv)
        self._apply_dark_theme()
        self.window = MainWindow(self.config)

    def _apply_dark_theme(self) -> None:
        """
        应用暗色主题样式表
        设置全局UI元素的颜色和背景
        """
        self.app.setStyle("Fusion")
        self.app.setStyleSheet("""
            QApplication { color: #d4d4d4; background-color: #2b2b2b; }
            QWidget { color: #d4d4d4; background-color: #2b2b2b; }
            QMenuBar { background-color: #2b2b2b; color: #d4d4d4; }
            QMenuBar::item { background-color: transparent; }
            QMenuBar::item:selected { background-color: #3c3c3c; }
            QMenu { background-color: #2b2b2b; color: #d4d4d4; border: 1px solid #555; }
            QMenu::item:selected { background-color: #3c3c3c; }
            QToolTip { background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #555; }
            QScrollBar:vertical { background-color: #2b2b2b; width: 12px; }
            QScrollBar::handle:vertical { background-color: #555; min-height: 20px; }
            QScrollBar::handle:vertical:hover { background-color: #666; }
            QScrollBar:horizontal { background-color: #2b2b2b; height: 12px; }
            QScrollBar::handle:horizontal { background-color: #555; min-width: 20px; }
            QScrollBar::handle:horizontal:hover { background-color: #666; }
        """)

    def _connect_signals(self) -> None:
        """
        连接所有信号与槽函数
        将窗口信号与对应的处理方法绑定
        """
        signal_map = {
            self.window.listen_start_signal: self.start_listening,
            self.window.listen_stop_signal: self.stop_listening,
            self.window.load_model_signal: self.load_model,
            self.window.recognition_start_signal: self.start_recognition,
            self.window.recognition_stop_signal: self.stop_recognition,
            self.window.translation_start_signal: self.start_translation,
            self.window.translation_stop_signal: self.stop_translation,
            self.window.device_changed_signal: self._on_device_changed,
            self.window.input_device_changed_signal: self._on_input_device_changed,
            self.window.loopback_device_changed_signal: self._on_loopback_device_changed,
            self.window.device_type_changed_signal: self._on_device_type_changed,
            self.window.volume_threshold_changed_signal: self._on_volume_threshold_changed,
            self.window.refresh_devices_signal: self._refresh_devices,
            self.window.volume_updated_signal: self.window.update_volume,
            self.window.recognition_text_updated_signal: self.window.update_recognition_text,
            self.window.translation_text_updated_signal: self.window.update_translation_text,
            self.window.translation_latest_text_updated_signal: self.window.update_translation_latest_text_only,
            self.window.instant_translate_changed_signal: self._on_instant_translate_changed,
            self.window.manual_translate_signal: self._on_manual_translate,
            self.window.status_message_signal: self.window.show_status_message,
            self.window.apply_settings_signal: self._on_apply_settings,
            self.window.clear_texts_signal: self._on_clear_texts,
            self.window.update_used_chars_signal: self._on_used_chars_updated,
            self.window.translation_status_updated_signal: self.window.update_translation_status
        }

        for signal, slot in signal_map.items():
            signal.connect(slot)

    # ========== 模块初始化部分 ==========
    def _init_modules(self) -> None:
        """
        初始化所有功能模块
        包括: 检查模型目录、初始化音频捕获、初始化翻译客户端
        """
        try:
            self._check_models_directory()
            self._init_audio_capture()
            self._init_translation_client()
            print("所有模块初始化完成")
        except Exception as e:
            print(f"模块初始化失败: {e}")
            self.window.show_error("初始化错误", f"模块初始化失败: {e}")

    def _check_models_directory(self) -> None:
        """
        检查语音识别模型目录是否存在
        如果不存在或为空则显示错误提示
        """
        try:
            models_dir = Path("models")
            if not models_dir.exists() or not any(models_dir.iterdir()):
                # 如果目录不存在或为空，直接弹出错误对话框
                print("\033[91m[ERROR] models 文件夹不存在或为空\033[0m")
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "你的运行环境下models文件夹为空，检查是否准备了语音识别模型\n下载地址:alphacephei.com/vosk/models",
                    "程序遇到一个错误 但你可以忽略它继续运行",
                    0x10
                )
        except Exception as e:
            # 捕获其他可能的异常（如权限问题等）
            print(f"\033[91m[ERROR] 检查models文件夹失败: {e}\033[0m")
            ctypes.windll.user32.MessageBoxW(
                0,
                f"无法检查models文件夹,查看控制台异常堆栈跟踪 {e}",
                "程序遇到一个错误 但你可以忽略它继续运行",
                0x10
            )
            print(f"\033[91m[DEBUG] 异常类型: {type(e)} 详细信息: {e}\033[0m")
            import traceback
            traceback.print_exc()  # 如果此步骤遇到错误 打印完整调用栈

    def _handle_missing_models(self) -> None:
        """
        处理模型缺失情况
        显示错误消息并提示用户下载模型
        """
        print("\033[91m[ERROR] models文件夹不存在或为空！\033[0m")
        print("\033[91m[ERROR] 请下载语音识别模型并放置在models目录下\033[0m")
        try:
            self.window.show_error("模型错误", "models文件夹不存在或为空！\n请下载语音识别模型并放置在models目录下")
        except Exception as e:
            print(f"\033[91m[ERROR] 无法显示错误对话框: {e}\033[0m")

    def _init_audio_capture(self) -> None:
        """
        初始化音频捕获模块
        包括: 获取设备列表、创建音频捕获对象
        """
        audio_config = self.config.get_audio_config()
        device_type = audio_config.get("device_type", "input")

        # 获取设备列表
        input_devices = self._get_input_devices(audio_config)
        loopback_devices = self._get_loopback_devices(audio_config)

        # 自动选择默认设备
        loopback_device_index = audio_config.get("loopback_device_index")
        loopback_device_index = self._auto_select_default_loopback(loopback_devices, loopback_device_index)

        # 更新GUI设备列表
        self._update_gui_device_list(
            input_devices,
            loopback_devices,
            audio_config.get("device_index"),
            loopback_device_index,
            device_type
        )

        # 创建捕获对象
        self._create_capture_objects(audio_config, device_type, loopback_device_index)

    def _get_input_devices(self, audio_config: dict) -> list:
        """
        获取输入音频设备列表

        Args:
            audio_config: 音频配置字典

        Returns:
            输入设备列表
        """
        try:
            temp_capture = AudioCapture(
                sample_rate=audio_config.get("sample_rate", 16000),
                channels=audio_config.get("channels", 1),
                process_interval_seconds=audio_config.get("process_interval_seconds", 3.0),
                format=audio_config.get("format", "int16"),
                device_index=None,
                sentence_break_interval=audio_config.get("sentence_break_interval", 2.0)
            )
            devices = temp_capture.get_available_devices()
            temp_capture.close()
            return devices
        except Exception as e:
            print(f"获取输入设备列表失败: {e}")
            return []

    def _get_loopback_devices(self, audio_config: dict) -> list:
        """
        获取桌面音频设备列表

        Args:
            audio_config: 音频配置字典

        Returns:
            桌面音频设备列表
        """
        try:
            temp_loopback = LoopbackAudioCapture(
                sample_rate=audio_config.get("sample_rate", 16000),
                channels=audio_config.get("channels", 1),
                process_interval_seconds=audio_config.get("process_interval_seconds", 3.0),
                format=audio_config.get("format", "int16"),
                device_index=None,
                sentence_break_interval=audio_config.get("sentence_break_interval", 2.0)
            )
            devices = temp_loopback.get_available_devices()
            temp_loopback.close()
            return devices
        except Exception as e:
            print(f"获取桌面音频设备列表失败: {e}")
            return []

    def _auto_select_default_loopback(self, loopback_devices: list, current_index: Optional[int]) -> Optional[int]:
        """
        自动选择默认loopback设备

        Args:
            loopback_devices: 桌面音频设备列表
            current_index: 当前选择的设备索引

        Returns:
            选择的设备索引或None
        """
        if current_index is None and loopback_devices:
            for device in loopback_devices:
                if device.get('isDefault', False):
                    current_index = device.get('index')
                    print(f"自动选择默认桌面音频设备: [{current_index}] {device.get('name', 'Unknown')}")
                    self.config.set("audio.loopback_device_index", current_index)
                    self.config.save()
                    break
        return current_index

    def _update_gui_device_list(self, input_devices: list, loopback_devices: list,
                               input_index: Optional[int], loopback_index: Optional[int],
                               device_type: str) -> None:
        """
        更新GUI中的设备列表显示

        Args:
            input_devices: 输入设备列表
            loopback_devices: 桌面音频设备列表
            input_index: 默认输入设备索引
            loopback_index: 默认桌面音频设备索引
            device_type: 当前选择的设备类型
        """
        self.window.update_device_list(
            input_devices,
            loopback_devices,
            default_input_index=input_index,
            default_loopback_index=loopback_index,
            device_type=device_type
        )

    def _create_capture_objects(self, audio_config: dict, device_type: str,
                              loopback_device_index: Optional[int]) -> None:
        """
        创建音频捕获对象

        Args:
            audio_config: 音频配置字典
            device_type: 设备类型 (input/loopback)
            loopback_device_index: 桌面音频设备索引
        """
        if device_type == "input" and audio_config.get("device_index") is not None:
            self.audio_capture = self._create_audio_capture(audio_config)
        elif device_type == "loopback" and loopback_device_index is not None:
            self.loopback_capture = self._create_loopback_capture(audio_config, loopback_device_index)

    def _create_audio_capture(self, audio_config: dict) -> AudioCapture:
        """
        创建音频输入捕获对象

        Args:
            audio_config: 音频配置字典

        Returns:
            初始化的AudioCapture实例
        """
        return AudioCapture(
            sample_rate=audio_config.get("sample_rate", 16000),
            channels=audio_config.get("channels", 1),
            process_interval_seconds=audio_config.get("process_interval_seconds", 3.0),
            format=audio_config.get("format", "int16"),
            callback=self._on_audio_chunk,
            volume_callback=self._on_volume_update,
            device_index=audio_config.get("device_index"),
            volume_threshold=audio_config.get("volume_threshold", 1.0),
            sentence_break_interval=audio_config.get("sentence_break_interval", 2.0)
        )

    def _create_loopback_capture(self, audio_config: dict, device_index: int) -> LoopbackAudioCapture:
        """
        创建桌面音频捕获对象

        Args:
            audio_config: 音频配置字典
            device_index: 设备索引

        Returns:
            初始化的LoopbackAudioCapture实例
        """
        return LoopbackAudioCapture(
            sample_rate=audio_config.get("sample_rate", 16000),
            channels=audio_config.get("channels", 1),
            process_interval_seconds=audio_config.get("process_interval_seconds", 3.0),
            format=audio_config.get("format", "int16"),
            callback=self._on_audio_chunk,
            volume_callback=self._on_volume_update,
            device_index=device_index,
            volume_threshold=audio_config.get("volume_threshold", 1.0),
            sentence_break_interval=audio_config.get("sentence_break_interval", 2.0)
        )

    def _init_translation_client(self) -> None:
        """初始化翻译客户端"""
        trans_config = self.config.get_translation_config()
        self.translation_client = TranslationClient(
            provider=trans_config.get("api_provider", "siliconflow"),
            api_key=trans_config.get("api_key", ""),
            api_url=trans_config.get("api_url", ""),
            model=trans_config.get("model", "deepseek-chat"),
            timeout=trans_config.get("timeout", 30),
            trans_config=trans_config
        )

    # ========== 音频处理部分 ==========
    def _on_audio_chunk(self, audio_data: bytes) -> None:
        """
        处理音频数据块
        包括: 验证数据、检查识别状态、分块处理

        Args:
            audio_data: 音频数据字节流
        """
        if not self._validate_audio_data(audio_data):
            return

        if not self._check_recognition_ready():
            return

        self._process_audio_chunks(audio_data)

    def _validate_audio_data(self, audio_data: bytes) -> bool:
        """
        验证音频数据有效性

        Args:
            audio_data: 音频数据字节流

        Returns:
            数据是否有效
        """
        if not audio_data or len(audio_data) == 0:
            print(f"[WARNING] 音频数据为空或长度为0，跳过处理")
            return False
        return True

    def _check_recognition_ready(self) -> bool:
        """
        检查语音识别是否就绪

        Returns:
            识别是否准备好
        """
        if not self.vosk_engine:
            print(f"[WARNING] vosk引擎未初始化，无法处理音频数据")
            print(f"[INFO] 提示: 请先加载语音识别模型并开启识别功能")
            return False

        if not self.is_recognizing:
            print(f"[WARNING] 识别未开启 (is_recognizing={self.is_recognizing})")
            print(f"[INFO] 提示: 请先开启识别功能")
            return False

        return True

    def _process_audio_chunks(self, audio_data: bytes) -> None:
        """
        处理音频数据块
        将音频数据分块传递给Vosk引擎

        Args:
            audio_data: 音频数据字节流
        """
        print(f"[DEBUG] 收到音频数据块 - 长度: {len(audio_data)} 字节, 准备传递给Vosk引擎")

        chunk_size = 4000  # Vosk推荐的大小
        chunk_count = 0
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i+chunk_size]
            if len(chunk) > 0:
                chunk_count += 1
                try:
                    self.vosk_engine.feed_audio(chunk)
                except Exception as e:
                    print(f"[ERROR] 传递音频块到Vosk引擎失败: {e}")
                    import traceback
                    traceback.print_exc()

        print(f"[DEBUG] 音频数据传递完成 - 总块数: {chunk_count}, 总长度: {len(audio_data)} 字节")

    def _on_volume_update(self, volume: float) -> None:
        """
        音量更新回调
        将音量值传递给UI更新

        Args:
            volume: 当前音量值(0-1)
        """
        self.window.volume_updated_signal.emit(volume)

    # ========== 识别结果处理部分 ==========
    def _on_recognition_result(self, text: str, is_final: bool,
                             spk_embedding=None, speaker_id=None, feature_hash="") -> None:
        """
        处理语音识别结果
        包括: 文本清理、说话人识别、UI更新、翻译请求

        Args:
            text: 识别出的文本
            is_final: 是否为最终结果
            spk_embedding: 说话人特征向量(可选)
            speaker_id: 说话人ID(可选)
            feature_hash: 特征哈希(可选)
        """
        if not text or not text.strip():
            return

        text = self._clean_recognition_text(text)

        if self._is_invalid_english_recognition(text):
            return

        speaker_display = self._get_speaker_display_info(is_final, speaker_id, feature_hash)
        self._update_recognition_ui(text, is_final, speaker_display)

        if self.is_translating:
            self._handle_translation_request(text, is_final, speaker_display.get('speaker_id'))

    def _clean_recognition_text(self, text: str) -> str:
        """
        清理识别文本(移除空格)

        Args:
            text: 原始识别文本

        Returns:
            清理后的文本
        """
        return text.replace(" ", "")

    def _is_invalid_english_recognition(self, text: str) -> bool:
        """
        检查是否为无效的英语识别结果("the")

        Args:
            text: 识别文本

        Returns:
            是否为无效结果
        """
        vosk_config = self.config.get_vosk_config()
        current_model = vosk_config.get("language", "")

        if current_model and ("en" in current_model.lower() or "english" in current_model.lower()):
            return text.strip().lower() == "the"
        return False

    def _get_speaker_display_info(self, is_final: bool, speaker_id: Optional[int],
                                feature_hash: str) -> dict:
        """
        获取说话人显示信息

        Args:
            is_final: 是否为最终结果
            speaker_id: 说话人ID
            feature_hash: 特征哈希

        Returns:
            包含说话人信息的字典
        """
        if is_final and speaker_id is not None:
            if hasattr(self.vosk_engine, 'speaker_profiles') and len(self.vosk_engine.speaker_profiles) > 1:
                return {
                    'speaker_id': speaker_id,
                    'feature_hash': feature_hash
                }
        return {}

    def _update_recognition_ui(self, text: str, is_final: bool, speaker_info: dict) -> None:
        """
        更新识别UI显示

        Args:
            text: 识别文本
            is_final: 是否为最终结果
            speaker_info: 说话人信息字典
        """
        self.window.recognition_text_updated_signal.emit(
            text,
            is_final,
            speaker_info.get('speaker_id'),
            speaker_info.get('feature_hash', "")
        )

    # ========== 翻译请求处理部分 ==========
    def _handle_translation_request(self, text: str, is_final: bool, speaker_id: Optional[int]) -> None:
        """
        处理翻译请求
        根据是否为最终结果和即时翻译设置决定请求类型

        Args:
            text: 要翻译的文本
            is_final: 是否为最终结果
            speaker_id: 说话人ID
        """
        if is_final:
            self.current_text = text
            context_prompt = self.context_manager.get_context()
            last_text = self.context_manager.get_last_text()
            self._request_translate(text, "full", context_prompt, last_text, speaker_id)
        elif self._should_instant_translate(text):
            self._request_translate(text, "instant", "", "", speaker_id)

    def _should_instant_translate(self, text: str) -> bool:
        """
        检查是否应该进行即时翻译

        Args:
            text: 待检查文本

        Returns:
            是否应该即时翻译
        """
        trans_config = self.config.get_translation_config()
        if not trans_config.get("instant_translate", False):
            return False
        return len(text.encode('utf-8')) > 8

    # ========== 翻译请求管理部分 ==========
    def _request_translate(self, text: str, request_type: str,
                          context_prompt: str = "", last_text: str = "",
                          speaker_id: Optional[int] = None) -> None:
        """
        请求翻译
        创建或更新待处理翻译请求

        Args:
            text: 要翻译的文本
            request_type: 请求类型 ("instant"或"full")
            context_prompt: 上下文提示(仅full类型)
            last_text: 上一句文本(仅full类型)
            speaker_id: 说话人ID
        """
        self._update_pending_request(text, request_type, context_prompt, last_text, speaker_id)

        if self.pending_translate_request and not self.is_waiting_for_response:
            self.translate_request_event.set()

    def _update_pending_request(self, text: str, request_type: str,
                              context_prompt: str, last_text: str,
                              speaker_id: Optional[int]) -> None:
        """
        更新待处理翻译请求
        根据请求类型处理合并逻辑

        Args:
            text: 要翻译的文本
            request_type: 请求类型
            context_prompt: 上下文提示
            last_text: 上一句文本
            speaker_id: 说话人ID
        """
        if request_type == "full":
            self._handle_full_translation_request(text, context_prompt, last_text, speaker_id)
        else:
            self._handle_instant_translation_request(text, speaker_id)

    def _handle_full_translation_request(self, text: str, context_prompt: str,
                                       last_text: str, speaker_id: Optional[int]) -> None:
        """
        处理完整翻译请求
        合并相同类型的请求

        Args:
            text: 要翻译的文本
            context_prompt: 上下文提示
            last_text: 上一句文本
            speaker_id: 说话人ID
        """
        if self.pending_translate_request and self.pending_translate_request["type"] == "full":
            # 合并请求
            existing_text = self.pending_translate_request.get("text", "")
            merged_text = existing_text + "\n" + text if existing_text else text
            self.pending_translate_request = {
                "text": merged_text,
                "type": "full",
                "context_prompt": context_prompt,
                "last_text": last_text,
                "speaker_id": speaker_id if speaker_id is not None else self.pending_translate_request.get("speaker_id")
            }
        else:
            # 新请求
            self.pending_translate_request = {
                "text": text,
                "type": "full",
                "context_prompt": context_prompt,
                "last_text": last_text,
                "speaker_id": speaker_id
            }

    def _handle_instant_translation_request(self, text: str, speaker_id: Optional[int]) -> None:
        """
        处理即时翻译请求
        优先处理完整翻译请求

        Args:
            text: 要翻译的文本
            speaker_id: 说话人ID
        """
        if self.pending_translate_request and self.pending_translate_request["type"] == "full":
            return  # 抛弃即时翻译请求

        self.pending_translate_request = {
            "text": text,
            "type": "instant",
            "context_prompt": "",
            "last_text": "",
            "speaker_id": speaker_id
        }

    # ========== 翻译结果解析部分 ==========
    def _parse_translation_result(self, result: str) -> Tuple[int, str]:
        """
        解析翻译结果
        尝试多种格式解析(JSON、分隔符、纯文本)

        Args:
            result: AI模型返回的原始字符串

        Returns:
            (权重, 翻译文本)
        """
        # 尝试JSON解析
        json_result = self._try_parse_json(result)
        if json_result:
            return json_result

        # 尝试分隔符解析
        delimiter_result = self._try_parse_delimiter(result)
        if delimiter_result:
            return delimiter_result

        # 默认解析
        return 100, result.strip()

    def _try_parse_json(self, result: str) -> Optional[Tuple[int, str]]:
        """
        尝试JSON解析翻译结果

        Args:
            result: 原始结果字符串

        Returns:
            (权重, 翻译文本) 或 None
        """
        import json
        import re

        try:
            result_stripped = result.strip()
            code_block_pattern = r'^```(?:json)?\s*\n?(.*?)\n?```\s*$'
            code_block_match = re.match(code_block_pattern, result_stripped, re.DOTALL)

            if code_block_match:
                result_stripped = code_block_match.group(1).strip()

            parsed = json.loads(result_stripped)
            if isinstance(parsed, dict):
                translation_text = self._extract_translation_text(parsed)
                ai_weight = self._extract_ai_weight(parsed)
                return 100 + ai_weight, translation_text
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return None

    def _extract_translation_text(self, parsed: dict) -> str:
        """
        从JSON解析结果中提取翻译文本

        Args:
            parsed: 解析后的字典

        Returns:
            翻译文本
        """
        if "t" in parsed:
            return str(parsed["t"])
        elif "text" in parsed:
            return str(parsed["text"])
        elif "translation" in parsed:
            return str(parsed["translation"])
        return json.dumps(parsed, ensure_ascii=False)

    def _extract_ai_weight(self, parsed: dict) -> int:
        """
        从JSON解析结果中提取AI权重

        Args:
            parsed: 解析后的字典

        Returns:
            AI权重值(0-99)
        """
        ai_weight = parsed.get("v", 0)
        if not isinstance(ai_weight, int) or ai_weight < 0 or ai_weight > 99:
            return 0
        return ai_weight

    def _try_parse_delimiter(self, result: str) -> Optional[Tuple[int, str]]:
        """
        尝试分隔符解析翻译结果

        Args:
            result: 原始结果字符串

        Returns:
            (权重, 翻译文本) 或 None
        """
        import re
        weight_match = re.match(r'^(\d{1,2})\|', result.strip())
        if weight_match:
            ai_weight = int(weight_match.group(1))
            if 0 <= ai_weight <= 99:
                return 100 + ai_weight, result[weight_match.end():].strip()
        return None

    # ========== 设备管理部分 ==========
    def _on_device_changed(self, device_index: int) -> None:
        """兼容旧代码的设备改变回调"""
        self._on_input_device_changed(device_index)

    def _on_input_device_changed(self, device_index: int) -> None:
        """
        输入设备改变回调
        更新配置并保存

        Args:
            device_index: 新设备索引
        """
        self.config.set("audio.device_index", device_index)
        self.config.set("audio.device_type", "input")
        self.config.save()
        self.window.status_bar.showMessage("输入设备已选择，将在下次开启监听时生效", 2000)

    def _on_loopback_device_changed(self, device_index: int) -> None:
        """
        桌面音频设备改变回调
        更新配置并保存

        Args:
            device_index: 新设备索引
        """
        self.config.set("audio.loopback_device_index", device_index)
        self.config.set("audio.device_type", "loopback")
        self.config.save()
        self.window.status_bar.showMessage("桌面音频设备已选择，将在下次开启监听时生效", 2000)

    def _on_device_type_changed(self, device_type: str) -> None:
        """
        设备类型改变回调
        更新配置并保存

        Args:
            device_type: 新设备类型 ("input"或"loopback")
        """
        self.config.set("audio.device_type", device_type)
        self.config.save()
        device_type_name = "输入设备" if device_type == "input" else "桌面音频"
        self.window.status_bar.showMessage(f"已切换到{device_type_name}，将在下次开启监听时生效", 2000)

    def _on_volume_threshold_changed(self, threshold: float) -> None:
        """
        音量阈值改变回调
        更新配置和音频捕获对象

        Args:
            threshold: 新音量阈值(0-1)
        """
        self.config.set("audio.volume_threshold", threshold)
        self.config.save()

        if self.audio_capture:
            self.audio_capture.volume_threshold = threshold
        if self.loopback_capture:
            self.loopback_capture.volume_threshold = threshold

        self.window.status_bar.showMessage(f"音量阈值已更新: {threshold}%", 2000)

    def _on_used_chars_updated(self, chars: int) -> None:
        """
        更新已消耗字符数显示

        Args:
            chars: 已使用字符数
        """
        if hasattr(self.window, '_update_used_chars_display'):
            self.window._update_used_chars_display(chars)

    # ========== 手动翻译处理部分 ==========
    def _on_manual_translate(self, text: str) -> None:
        """
        处理手动翻译请求
        包括: 输入验证、模拟识别、发送翻译请求

        Args:
            text: 要翻译的文本
        """
        if not text or not text.strip():
            return

        if not self._check_api_key():
            self.window.show_error("配置错误", "请先设置API密钥")
            return

        self._simulate_recognition(text)
        self._request_manual_translation(text)

    def _check_api_key(self) -> bool:
        """
        检查API密钥是否设置

        Returns:
            是否设置了API密钥
        """
        trans_config = self.config.get_translation_config()
        return bool(trans_config.get("api_key"))

    def _simulate_recognition(self, text: str) -> None:
        """模拟识别结果显示"""
        self.window.update_recognition_text_for_test(text)

    def _request_manual_translation(self, text: str) -> None:
        """
        请求手动翻译
        创建完整翻译请求

        Args:
            text: 要翻译的文本
        """
        context_prompt = self.context_manager.get_context()
        last_text = self.context_manager.get_last_text()
        self._request_translate(text, "full", context_prompt, last_text)

    # ========== 核心功能控制部分 ==========
    def start_listening(self) -> None:
        """
        开启音频监听
        根据设备类型启动相应的音频捕获
        """
        if self.is_listening:
            return

        try:
            audio_config = self.config.get_audio_config()
            device_type = audio_config.get("device_type", "input")

            if device_type == "input":
                self._start_input_listening(audio_config)
            else:
                self._start_loopback_listening(audio_config)

            self.is_listening = True
            self.window.set_listening_state(True)
            device_type_name = "输入设备" if device_type == "input" else "桌面音频"
            self.window.status_bar.showMessage(f"监听已开启 ({device_type_name})", 2000)
        except Exception as e:
            print(f"开启监听失败: {e}")
            self.window.show_error("错误", f"开启监听失败: {e}")

    def _start_input_listening(self, audio_config: dict) -> None:
        """
        启动输入设备监听

        Args:
            audio_config: 音频配置字典
        """
        device_index = audio_config.get("device_index")
        if device_index is None:
            raise ValueError("请先选择输入设备")

        if not self.audio_capture or self.audio_capture.device_index != device_index:
            if self.audio_capture:
                self.audio_capture.close()
            self.audio_capture = self._create_audio_capture(audio_config)

        self.audio_capture.start()

    def _start_loopback_listening(self, audio_config: dict) -> None:
        """
        启动桌面音频监听

        Args:
            audio_config: 音频配置字典
        """
        loopback_device_index = self._get_loopback_device_index(audio_config)
        if loopback_device_index is None:
            raise ValueError("请先选择桌面音频设备")

        if not self.loopback_capture or self.loopback_capture.device_index != loopback_device_index:
            if self.loopback_capture:
                self.loopback_capture.close()
            self.loopback_capture = self._create_loopback_capture(audio_config, loopback_device_index)

        self.loopback_capture.start()

    def _get_loopback_device_index(self, audio_config: dict) -> Optional[int]:
        """
        获取loopback设备索引
        自动选择默认设备

        Args:
            audio_config: 音频配置字典

        Returns:
            设备索引或None
        """
        loopback_device_index = audio_config.get("loopback_device_index")
        if loopback_device_index is not None:
            return loopback_device_index

        # 尝试自动选择默认设备
        temp_loopback = LoopbackAudioCapture(
            sample_rate=audio_config.get("sample_rate", 16000),
            channels=audio_config.get("channels", 1),
            process_interval_seconds=audio_config.get("process_interval_seconds", 3.0),
            format=audio_config.get("format", "int16"),
            device_index=None,
            sentence_break_interval=audio_config.get("sentence_break_interval", 2.0)
        )

        try:
            loopback_devices = temp_loopback.get_available_devices()
            for device in loopback_devices:
                if device.get('isDefault', False):
                    loopback_device_index = device.get('index')
                    print(f"自动选择默认桌面音频设备: [{loopback_device_index}] {device.get('name', 'Unknown')}")
                    self.config.set("audio.loopback_device_index", loopback_device_index)
                    self.config.save()
                    return loopback_device_index
        finally:
            temp_loopback.close()

        return None

    def stop_listening(self) -> None:
        """
        关闭音频监听
        停止相关服务和音频捕获
        """
        if not self.is_listening:
            return

        try:
            self._stop_related_services()

            if self.audio_capture:
                self.audio_capture.stop()
            if self.loopback_capture:
                self.loopback_capture.stop()

            self.is_listening = False
            self.window.set_listening_state(False)
            self.window.update_volume(0.0)
            self.window.status_bar.showMessage("监听已关闭", 2000)
        except Exception as e:
            print(f"关闭监听失败: {e}")

    def _stop_related_services(self) -> None:
        """停止相关的识别和翻译服务"""
        if self.is_recognizing:
            self.stop_recognition()
        if self.is_translating:
            self.stop_translation()

    def load_model(self) -> None:
        """
        加载/重载语音识别模型
        包括: 模型选择、Vosk引擎初始化、状态更新
        """
        try:
            model_folder = self._get_selected_model()
            if not model_folder:
                self.window.show_error("错误", "请先选择一个有效的模型")
                return

            self._reload_vosk_model(model_folder)

            if self.vosk_engine.model is None:
                self._handle_model_load_failure(model_folder)
                return

            self._handle_successful_model_load(model_folder)

        except Exception as e:
            print(f"加载模型失败: {e}")
            self.window.show_error("错误", f"加载模型失败: {e}")
            self.model_loaded = False
            self.window.set_model_loaded("")

    def _get_selected_model(self) -> Optional[str]:
        """
        获取当前选择的模型文件夹名

        Returns:
            模型文件夹名或None
        """
        return self.window.language_combo.itemData(self.window.language_combo.currentIndex())

    def _reload_vosk_model(self, model_folder: str) -> None:
        """
        重载Vosk语音识别模型

        Args:
            model_folder: 模型文件夹名
        """
        if self.vosk_engine:
            if self.is_recognizing:
                self.vosk_engine.stop()
            self.vosk_engine = None

        vosk_config = self.config.get_vosk_config()
        audio_config = self.config.get_audio_config()

        self.vosk_engine = VoskEngine(
            model_path=vosk_config.get("model_path", "models"),
            language=model_folder,
            sample_rate=audio_config.get("sample_rate", 16000),
            callback=self._on_recognition_result
        )

    def _handle_model_load_failure(self, model_folder: str) -> None:
        """
        处理模型加载失败情况

        Args:
            model_folder: 模型文件夹名
        """
        self.window.set_model_loaded("")
        self.window.show_error("错误", f"未找到模型: {model_folder}")
        self.model_loaded = False

    def _handle_successful_model_load(self, model_folder: str) -> None:
        """
        处理模型加载成功情况
        更新UI显示和状态

        Args:
            model_folder: 模型文件夹名
        """
        model_path = Path(self.config.get_vosk_config().get("model_path", "models")) / model_folder
        self.window.set_model_loaded(str(model_path))
        self.model_loaded = True
        self.window.status_bar.showMessage(f"模型加载成功: {model_folder}", 2000)
        self._on_clear_texts()

    def start_recognition(self) -> None:
        """
        开启语音识别
        检查前置条件后启动Vosk引擎
        """
        if self.is_recognizing:
            return

        if not self._check_listening_state():
            return

        if not self._check_model_loaded():
            return

        try:
            if self.vosk_engine:
                self.vosk_engine.start()
            self.is_recognizing = True
            self.window.set_recognition_state(True)
            self.window.clear_recognition_text()
            self.window.status_bar.showMessage("识别已开启", 2000)
        except Exception as e:
            print(f"开启识别失败: {e}")
            self.window.show_error("错误", f"开启识别失败: {e}")

    def _check_listening_state(self) -> bool:
        """
        检查监听状态是否开启

        Returns:
            监听是否开启
        """
        if not self.is_listening:
            self.window.show_error("错误", "请先开启监听")
            return False
        return True

    def _check_model_loaded(self) -> bool:
        """
        检查语音识别模型是否加载

        Returns:
            模型是否加载
        """
        if not self.model_loaded or not self.vosk_engine:
            self.window.show_error("错误", "请先加载语音识别模型")
            return False
        return True

    def stop_recognition(self) -> None:
        """
        关闭语音识别
        停止Vosk引擎和翻译服务
        """
        if not self.is_recognizing:
            return

        try:
            if self.is_translating:
                self.stop_translation()

            if self.vosk_engine:
                self.vosk_engine.stop()
            self.is_recognizing = False
            self.window.set_recognition_state(False)
            self.window.status_bar.showMessage("识别已关闭", 2000)
        except Exception as e:
            print(f"关闭识别失败: {e}")

    def _check_translation_config(self) -> Tuple[bool, str]:
        """
        检查翻译配置是否完整

        Returns:
            (配置是否完整, 错误消息)
        """
        trans_config = self.config.get_translation_config()
        use_ai = trans_config.get("use_ai_translation", True)
        machine_config = trans_config.get("machine_translation", {})

        if use_ai:
            if not self._check_ai_translation_config(trans_config, machine_config):
                return False, "AI翻译需要设置API密钥"
        elif not self._check_machine_translation_config(machine_config):
            return False, "机器翻译需要设置腾讯云SecretId和SecretKey"

        return True, ""

    def _check_ai_translation_config(self, trans_config: dict, machine_config: dict) -> bool:
        """
        检查AI翻译配置
        验证API密钥和腾讯云凭据

        Args:
            trans_config: 翻译配置
            machine_config: 机器翻译配置

        Returns:
            配置是否有效
        """
        if not self.translation_client or not self.translation_client.api_key:
            return False

        instant_use_machine = trans_config.get("instant_use_machine_translation", True)
        if instant_use_machine:
            if not machine_config.get("tencent_secret_id") or not machine_config.get("tencent_secret_key"):
                return False

        return True

    def _check_machine_translation_config(self, machine_config: dict) -> bool:
        """
        检查机器翻译配置
        验证腾讯云凭据

        Args:
            machine_config: 机器翻译配置

        Returns:
            配置是否有效
        """
        return bool(machine_config.get("tencent_secret_id") and machine_config.get("tencent_secret_key"))

    def start_translation(self) -> None:
        """
        开启翻译服务
        初始化翻译状态并启动翻译线程
        """
        if self.is_translating:
            return

        if not self._check_recognition_state():
            return

        config_ok, error_msg = self._check_translation_config()
        if not config_ok:
            self.window.show_error("配置错误", error_msg)
            return

        try:
            self._init_translation_state()

            if not self.translate_thread_running:
                self._start_translation_thread()

            self._update_translation_ui()
        except Exception as e:
            print(f"开启翻译失败: {e}")
            self.window.show_error("错误", f"开启翻译失败: {e}")

    def _check_recognition_state(self) -> bool:
        """
        检查识别状态是否开启

        Returns:
            识别是否开启
        """
        if not self.is_recognizing:
            self.window.show_error("错误", "请先开启识别")
        return bool(self.is_recognizing)

    def _init_translation_state(self) -> None:
        """初始化翻译状态变量"""
        self.context_manager.clear()
        self.pending_translate_request = None
        self.is_waiting_for_response = False
        self.last_translate_time = 0.0
        self.is_translating = True

    def _start_translation_thread(self) -> None:
        """启动翻译工作线程"""
        self.translate_thread_stop.clear()
        self.translate_thread_running = True
        self.translate_thread = threading.Thread(target=self._translate_worker_loop, daemon=True)
        self.translate_thread.start()

    def _update_translation_ui(self) -> None:
        """更新翻译UI状态"""
        self.window.set_translation_state(True)
        self.window.clear_translation_texts()
        self.window.translation_status_updated_signal.emit(
            self.is_translating,
            self.is_waiting_for_response,
            self.translate_times.copy()
        )
        self.window.status_bar.showMessage("翻译已开启", 2000)

    def stop_translation(self) -> None:
        """
        关闭翻译服务
        停止翻译线程并更新状态
        """
        if not self.is_translating:
            return

        try:
            self.pending_translate_request = None
            self.is_translating = False
            self.is_waiting_for_response = False
            self.window.set_translation_state(False)
            self.window.translation_status_updated_signal.emit(
                self.is_translating,
                self.is_waiting_for_response,
                self.translate_times.copy()
            )
            self.window.status_bar.showMessage("翻译已关闭", 2000)
        except Exception as e:
            print(f"关闭翻译失败: {e}")

    # ========== 设备刷新部分 ==========
    def _refresh_devices(self) -> None:
        """
        刷新音频设备列表
        更新输入和桌面音频设备列表
        """
        try:
            audio_config = self.config.get_audio_config()
            input_devices = self._get_input_devices(audio_config)
            loopback_devices = self._get_loopback_devices(audio_config)

            loopback_device_index = self._auto_select_default_loopback(
                loopback_devices,
                audio_config.get("loopback_device_index")
            )

            self._update_gui_device_list(
                input_devices,
                loopback_devices,
                audio_config.get("device_index"),
                loopback_device_index,
                audio_config.get("device_type", "input")
            )
        except Exception as e:
            print(f"刷新设备列表失败: {e}")
            self.window.show_error("错误", f"刷新设备列表失败: {e}")

    # ========== 文本处理部分 ==========
    def _on_clear_texts(self) -> None:
        """清空所有文本和上下文"""
        self.window.clear_all_texts()
        self.context_manager.clear()
        print("已清空所有文本和上下文缓存")

    def _on_instant_translate_changed(self, enabled: bool) -> None:
        """
        处理即时翻译设置改变

        Args:
            enabled: 是否启用即时翻译
        """
        print(f"即时翻译设置已更新: {'启用' if enabled else '禁用'}")

    # ========== 设置应用部分 ==========
    def _on_apply_settings(self) -> None:
        """
        应用所有设置
        保存并更新各个模块的配置
        """
        try:
            self._save_audio_settings()
            self._save_vosk_settings()
            self._save_translation_settings()
            self._save_memory_settings()
            self._save_prompt_settings()
            self._save_instant_settings()
            self._save_machine_translation_settings()

            self.config.save()
            self._update_client_config()
            self._update_context_manager()

            self.window.status_message_signal.emit("设置已保存", 2000)
            print("设置已保存到配置文件")
        except Exception as e:
            print(f"保存设置失败: {e}")
            self.window.show_error("错误", f"保存设置失败: {e}")

    def _save_audio_settings(self) -> None:
        """保存音频相关设置"""
        if hasattr(self.window, 'audio_process_interval_spin'):
            self.config.set("audio.process_interval_seconds", self.window.audio_process_interval_spin.value())
        if hasattr(self.window, 'audio_sentence_break_interval_spin'):
            self.config.set("audio.sentence_break_interval", self.window.audio_sentence_break_interval_spin.value())
        if hasattr(self.window, 'audio_format_combo'):
            self.config.set("audio.format", self.window.audio_format_combo.currentText())

    def _save_vosk_settings(self) -> None:
        """保存Vosk相关设置"""
        if hasattr(self.window, 'vosk_model_path_edit'):
            self.config.set("vosk.model_path", self.window.vosk_model_path_edit.text())

    def _save_translation_settings(self) -> None:
        """保存翻译相关设置"""
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

    def _save_memory_settings(self) -> None:
        """保存记忆相关设置"""
        if hasattr(self.window, 'trans_memory_count_spin'):
            self.config.set("translation.memory_max_count", self.window.trans_memory_count_spin.value())
        if hasattr(self.window, 'trans_memory_time_spin'):
            self.config.set("translation.memory_time", self.window.trans_memory_time_spin.value())

    def _save_prompt_settings(self) -> None:
        """保存提示词相关设置"""
        if hasattr(self.window, 'prompt_template_edit'):
            self.config.set("translation.prompt_template", self.window.prompt_template_edit.toPlainText())
        if hasattr(self.window, 'instant_prompt_template_edit'):
            self.config.set("translation.instant_prompt_template", self.window.instant_prompt_template_edit.toPlainText())

    def _save_instant_settings(self) -> None:
        """保存即时翻译设置"""
        if hasattr(self.window, 'instant_translate_checkbox'):
            self.config.set("translation.instant_translate", self.window.instant_translate_checkbox.isChecked())

    def _save_machine_translation_settings(self) -> None:
        """保存机器翻译设置"""
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

    def _update_client_config(self) -> None:
        """更新翻译客户端配置"""
        if self.translation_client:
            trans_config = self.config.get_translation_config()
            self.translation_client.update_config(
                api_key=self.config.get("translation.api_key", ""),
                api_url=self.config.get("translation.api_url", ""),
                model=self.config.get("translation.model", "deepseek-chat"),
                trans_config=trans_config
            )

    def _update_context_manager(self) -> None:
        """更新上下文管理器配置"""
        trans_config = self.config.get_translation_config()
        self.context_manager.update_config(
            max_count=trans_config.get("memory_max_count", 10),
            memory_time=trans_config.get("memory_time", 300.0)
        )

    # ========== 主运行循环部分 ==========
    def run(self) -> int:
        """
        运行应用程序主循环

        Returns:
            应用程序退出代码
        """
        self.window.show()
        return self.app.exec()

    def cleanup(self) -> None:
        """
        清理应用程序资源
        停止所有服务并关闭模块
        """
        self._stop_all_services()
        self._stop_translation_thread()
        self._close_modules()

    def _stop_all_services(self) -> None:
        """停止所有运行中的服务"""
        if self.is_translating:
            self.stop_translation()
        if self.is_recognizing:
            self.stop_recognition()
        if self.is_listening:
            self.stop_listening()

    def _stop_translation_thread(self) -> None:
        """停止翻译工作线程"""
        if self.translate_thread_running:
            self.translate_thread_stop.set()
            self.translate_request_event.set()

            if self.translate_thread and self.translate_thread.is_alive():
                print("等待翻译线程结束...")
                self.translate_thread.join(timeout=3.0)
                if self.translate_thread.is_alive():
                    print("警告: 翻译线程未在超时时间内完成")

            self.translate_thread_running = False

    def _close_modules(self) -> None:
        """关闭所有模块"""
        if self.audio_capture:
            self.audio_capture.close()
        if self.loopback_capture:
            self.loopback_capture.close()
        if self.translation_client:
            self.translation_client.close()

def main() -> int:
    """
    应用程序主入口
    创建并运行应用程序实例

    Returns:
        应用程序退出代码
    """
    app = None
    try:
        app = TranslatorApp()
        return app.run()
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
