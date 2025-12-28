"""
PyQt6主窗口
"""
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTextEdit, QLabel, QComboBox,
                             QLineEdit, QGroupBox, QStatusBar, QMessageBox,
                             QSplitter, QProgressBar, QTabWidget, QSpinBox,
                             QDoubleSpinBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette
from typing import Optional, Callable, Dict, Any
import sys

class MainWindow(QMainWindow):
    """主窗口类"""
    
    # 信号定义
    listen_start_signal = pyqtSignal()  # 开启监听
    listen_stop_signal = pyqtSignal()  # 关闭监听
    load_model_signal = pyqtSignal()  # 加载模型
    recognition_start_signal = pyqtSignal()  # 开启识别
    recognition_stop_signal = pyqtSignal()  # 关闭识别
    translation_start_signal = pyqtSignal()  # 开启翻译
    translation_stop_signal = pyqtSignal()  # 关闭翻译
    language_changed_signal = pyqtSignal(str)  # 语言改变（仅用于下拉框选择，不加载模型）
    device_changed_signal = pyqtSignal(int)  # 设备索引（已废弃，保留兼容性）
    input_device_changed_signal = pyqtSignal(int)  # 输入设备索引
    loopback_device_changed_signal = pyqtSignal(int)  # 桌面音频设备索引
    device_type_changed_signal = pyqtSignal(str)  # 设备类型改变信号 ("input" 或 "loopback")
    refresh_devices_signal = pyqtSignal()  # 刷新设备列表
    volume_threshold_changed_signal = pyqtSignal(float)  # 音量阈值改变信号
    volume_updated_signal = pyqtSignal(float)  # 音量更新信号
    recognition_text_updated_signal = pyqtSignal(str, bool, object, str)  # 识别文本更新信号 (text, is_final, speaker_id, feature_hash)
    translation_text_updated_signal = pyqtSignal(str, object)  # 翻译文本更新信号（完整句子，更新最近和历史）(text, speaker_id)
    translation_latest_text_updated_signal = pyqtSignal(str, object)  # 即时翻译文本更新信号（只更新最近）(text, speaker_id)
    instant_translate_changed_signal = pyqtSignal(bool)  # 即时翻译设置改变信号
    translation_status_updated_signal = pyqtSignal(bool, bool, list)  # 翻译状态更新信号 (is_translating, is_waiting, translate_times)
    update_used_chars_signal = pyqtSignal(int)  # 更新已消耗字符数信号
    manual_translate_signal = pyqtSignal(str)  # 手动翻译信号
    status_message_signal = pyqtSignal(str, int)  # 状态栏消息信号 (message, timeout_ms)
    apply_settings_signal = pyqtSignal()  # 应用设置信号（会重启程序）
    clear_texts_signal = pyqtSignal()  # 清空文本信号
    
    def __init__(self, config, parent=None):
        """
        初始化主窗口
        
        Args:
            config: 配置对象
            parent: 父窗口
        """
        super().__init__(parent)
        self.config = config
        self.is_listening = False
        self.is_recognizing = False
        self.is_translating = False
        self.model_folders = []  # 初始化模型文件夹列表
        
        # 连接翻译状态更新信号
        self.translation_status_updated_signal.connect(self.update_translation_status)
        # 连接更新字符数信号
        self.update_used_chars_signal.connect(self._on_used_chars_updated)
        
        self.init_ui()
        self.apply_config()
    
    def init_ui(self) -> None:
        """初始化UI"""
        self.setWindowTitle("翻译器")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 创建分页控件
        self.tab_widget = QTabWidget()
        
        # 第一页：主界面
        main_page = self._create_main_page()
        self.tab_widget.addTab(main_page, "主界面")
        
        # 第二页：设置
        settings_page = self._create_settings_page()
        self.tab_widget.addTab(settings_page, "设置")
        
        main_layout.addWidget(self.tab_widget)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
        # 应用样式
        self._apply_style()
    
    def _create_main_page(self) -> QWidget:
        """创建主界面页面（横版布局：三列）"""
        page = QWidget()
        layout = QHBoxLayout(page)
        
        # 第一列：控制面板
        control_column = QWidget()
        control_layout = QVBoxLayout(control_column)
        
        # 音频设备选择面板
        device_group = self._create_device_panel()
        control_layout.addWidget(device_group)
        
        # 监听控制面板
        listen_group = self._create_listen_panel()
        control_layout.addWidget(listen_group)
        
        # 模型控制面板
        model_group = self._create_model_panel()
        control_layout.addWidget(model_group)
        
        # 识别控制面板
        recognition_control_group = self._create_recognition_control_panel()
        control_layout.addWidget(recognition_control_group)
        
        # 翻译控制面板
        translation_control_group = self._create_translation_control_panel()
        control_layout.addWidget(translation_control_group)
        
        control_layout.addStretch()
        
        # 第二列：识别文本
        recognition_group = self._create_recognition_panel()
        
        # 第三列：翻译结果
        translation_group = self._create_translation_panel()
        
        # 使用分割器布局三列
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(control_column)
        splitter.addWidget(recognition_group)
        splitter.addWidget(translation_group)
        
        # 设置列宽比例
        splitter.setStretchFactor(0, 0)  # 控制面板固定宽度
        splitter.setStretchFactor(1, 1)  # 识别文本可拉伸
        splitter.setStretchFactor(2, 1)  # 翻译结果可拉伸
        
        # 设置初始宽度
        splitter.setSizes([300, 400, 400])
        
        layout.addWidget(splitter)
        
        return page
    
    def _create_settings_page(self) -> QWidget:
        """创建设置页面（横版布局：两列）"""
        page = QWidget()
        layout = QHBoxLayout(page)
        
        # 第一列：所有设置（音频、Vosk、翻译）
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        
        # 音频设置
        audio_group = self._create_audio_settings()
        left_layout.addWidget(audio_group)
        
        # Vosk设置
        vosk_group = self._create_vosk_settings()
        left_layout.addWidget(vosk_group)
        
        # 翻译设置
        translation_group = self._create_translation_settings()
        left_layout.addWidget(translation_group)
        
        left_layout.addStretch()
        
        # 应用按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.apply_settings_btn = QPushButton("应用设置并重启")
        self.apply_settings_btn.clicked.connect(self._on_apply_settings_clicked)
        button_layout.addWidget(self.apply_settings_btn)
        left_layout.addLayout(button_layout)
        
        # 第二列：提示词设置
        prompt_group = self._create_prompt_settings()
        
        # 使用分割器布局两列
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_column)
        splitter.addWidget(prompt_group)
        
        # 设置列宽比例
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        # 设置初始宽度
        splitter.setSizes([600, 400])
        
        layout.addWidget(splitter)
        
        return page
    
    def _create_prompt_settings(self) -> QGroupBox:
        """创建提示词设置面板"""
        group = QGroupBox("提示词设置")
        layout = QVBoxLayout()
        
        trans_config = self.config.get_translation_config()
        
        # 使用分割器实现上下布局
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 上半部分：普通提示词
        normal_group = QGroupBox("普通提示词")
        normal_layout = QVBoxLayout(normal_group)
        info_label = QLabel("使用 {context} 和 {text} 作为占位符\n当无上下文时，{context} 将自动替换为\"当前新对话\"")
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        normal_layout.addWidget(info_label)
        
        self.prompt_template_edit = QTextEdit()
        self.prompt_template_edit.setPlaceholderText("输入提示词模板...")
        # 优先使用prompt_template
        prompt_template = trans_config.get("prompt_template", "")
        if prompt_template:
            self.prompt_template_edit.setPlainText(prompt_template)
        normal_layout.addWidget(self.prompt_template_edit)
        normal_group.setLayout(normal_layout)
        
        # 下半部分：即时翻译提示词
        instant_group = QGroupBox("即时翻译提示词")
        instant_layout = QVBoxLayout(instant_group)
        instant_info_label = QLabel("使用 {text} 作为占位符，用于部分识别结果的即时翻译")
        instant_info_label.setStyleSheet("color: #888; font-size: 11px;")
        instant_layout.addWidget(instant_info_label)
        
        self.instant_prompt_template_edit = QTextEdit()
        self.instant_prompt_template_edit.setPlaceholderText("输入即时翻译提示词模板...")
        instant_prompt_template = trans_config.get("instant_prompt_template", "")
        if instant_prompt_template:
            self.instant_prompt_template_edit.setPlainText(instant_prompt_template)
        instant_layout.addWidget(self.instant_prompt_template_edit)
        instant_group.setLayout(instant_layout)
        
        splitter.addWidget(normal_group)
        splitter.addWidget(instant_group)
        
        # 设置高度比例 3:1
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 100])
        
        layout.addWidget(splitter)
        group.setLayout(layout)
        return group
    
    def _create_audio_settings(self) -> QGroupBox:
        """创建音频设置面板"""
        group = QGroupBox("音频设置(输入Vosk识别模型)")
        layout = QVBoxLayout()
        
        audio_config = self.config.get_audio_config()
        
        # 采样率（只读，用于Vosk引擎）
        rate_layout = QHBoxLayout()
        rate_layout.addWidget(QLabel("采样率 (Hz):"))
        # 注意：此参数是传入Vosk引擎的音频参数，非输入设备参数
        # 输入设备可能使用不同的采样率，程序会自动重采样到此处设置的值
        self.audio_sample_rate_label = QLabel(str(audio_config.get("sample_rate", 16000)))
        self.audio_sample_rate_label.setStyleSheet("color: #888; font-style: italic;")
        rate_layout.addWidget(self.audio_sample_rate_label)
        rate_layout.addStretch()
        layout.addLayout(rate_layout)
        
        # 声道数（只读，用于Vosk引擎）
        channels_layout = QHBoxLayout()
        channels_layout.addWidget(QLabel("声道数:"))
        # 注意：此参数是传入Vosk引擎的音频参数，非输入设备参数
        # 输入设备可能使用多声道，程序会自动转换为单声道
        self.audio_channels_label = QLabel(str(audio_config.get("channels", 1)))
        self.audio_channels_label.setStyleSheet("color: #888; font-style: italic;")
        channels_layout.addWidget(self.audio_channels_label)
        channels_layout.addStretch()
        layout.addLayout(channels_layout)
        
        # 处理间隔（秒）
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("处理间隔 (秒):"))
        self.audio_process_interval_spin = QDoubleSpinBox()
        self.audio_process_interval_spin.setRange(0.5, 10.0)
        self.audio_process_interval_spin.setSingleStep(0.5)
        self.audio_process_interval_spin.setValue(audio_config.get("process_interval_seconds", 3.0))
        self.audio_process_interval_spin.setDecimals(1)
        interval_layout.addWidget(self.audio_process_interval_spin)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)
        
        # 断句间隔（秒）
        break_interval_layout = QHBoxLayout()
        break_interval_layout.addWidget(QLabel("断句间隔 (秒):"))
        self.audio_sentence_break_interval_spin = QDoubleSpinBox()
        self.audio_sentence_break_interval_spin.setRange(0.5, 10.0)
        self.audio_sentence_break_interval_spin.setSingleStep(0.5)
        self.audio_sentence_break_interval_spin.setValue(audio_config.get("sentence_break_interval", 2.0))
        self.audio_sentence_break_interval_spin.setDecimals(1)
        break_interval_layout.addWidget(self.audio_sentence_break_interval_spin)
        break_interval_layout.addStretch()
        layout.addLayout(break_interval_layout)
        
        # 音频格式
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("音频格式:"))
        self.audio_format_combo = QComboBox()
        self.audio_format_combo.addItems(["int16", "int32", "float32"])
        current_format = audio_config.get("format", "int16")
        index = self.audio_format_combo.findText(current_format)
        if index >= 0:
            self.audio_format_combo.setCurrentIndex(index)
        format_layout.addWidget(self.audio_format_combo)
        format_layout.addStretch()
        layout.addLayout(format_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_vosk_settings(self) -> QGroupBox:
        """创建Vosk设置面板"""
        group = QGroupBox("语音识别设置")
        layout = QVBoxLayout()
        
        vosk_config = self.config.get_vosk_config()
        
        # 模型路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("模型路径:"))
        self.vosk_model_path_edit = QLineEdit()
        self.vosk_model_path_edit.setText(vosk_config.get("model_path", "models"))
        path_layout.addWidget(self.vosk_model_path_edit)
        layout.addLayout(path_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_translation_settings(self) -> QGroupBox:
        """创建翻译设置面板"""
        group = QGroupBox("翻译设置")
        layout = QVBoxLayout()
        
        trans_config = self.config.get_translation_config()
        machine_config = trans_config.get("machine_translation", {})
        
        # 使用分割器实现上下布局
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 上半部分：AI翻译设置
        ai_group = QGroupBox("AI翻译")
        ai_layout = QVBoxLayout(ai_group)
        
        # API提供商和API密钥在同一行
        provider_key_layout = QHBoxLayout()
        provider_key_layout.addWidget(QLabel("API提供商:"))
        self.trans_provider_combo = QComboBox()
        self.trans_provider_combo.addItems(["siliconflow", "openai", "custom"])
        current_provider = trans_config.get("api_provider", "siliconflow")
        index = self.trans_provider_combo.findText(current_provider)
        if index >= 0:
            self.trans_provider_combo.setCurrentIndex(index)
        provider_key_layout.addWidget(self.trans_provider_combo)
        provider_key_layout.addWidget(QLabel("API密钥:"))
        self.trans_api_key_edit = QLineEdit()
        self.trans_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.trans_api_key_edit.setText(trans_config.get("api_key", ""))
        provider_key_layout.addWidget(self.trans_api_key_edit)
        provider_key_layout.addStretch()
        ai_layout.addLayout(provider_key_layout)
        
        # API地址和模型名称在同一行
        url_model_layout = QHBoxLayout()
        url_model_layout.addWidget(QLabel("API地址:"))
        self.trans_api_url_edit = QLineEdit()
        self.trans_api_url_edit.setText(trans_config.get("api_url", ""))
        url_model_layout.addWidget(self.trans_api_url_edit)
        url_model_layout.addWidget(QLabel("模型名称:"))
        self.trans_model_edit = QLineEdit()
        self.trans_model_edit.setText(trans_config.get("model", "deepseek-ai/DeepSeek-V3"))
        url_model_layout.addWidget(self.trans_model_edit)
        url_model_layout.addStretch()
        ai_layout.addLayout(url_model_layout)
        
        # 超时时间、Max Tokens、Temperature在同一行
        params_layout = QHBoxLayout()
        params_layout.addWidget(QLabel("超时时间 (秒):"))
        self.trans_timeout_spin = QSpinBox()
        self.trans_timeout_spin.setRange(5, 300)
        self.trans_timeout_spin.setValue(trans_config.get("timeout", 30))
        self.trans_timeout_spin.setMaximumWidth(80)
        params_layout.addWidget(self.trans_timeout_spin)
        params_layout.addWidget(QLabel("最大Token数:"))
        self.trans_max_tokens_spin = QSpinBox()
        self.trans_max_tokens_spin.setRange(100, 32000)
        self.trans_max_tokens_spin.setValue(trans_config.get("max_tokens", 8000))
        self.trans_max_tokens_spin.setMaximumWidth(100)
        params_layout.addWidget(self.trans_max_tokens_spin)
        params_layout.addWidget(QLabel("Temperature:"))
        self.trans_temperature_spin = QDoubleSpinBox()
        self.trans_temperature_spin.setRange(0.0, 2.0)
        self.trans_temperature_spin.setSingleStep(0.1)
        self.trans_temperature_spin.setDecimals(1)
        self.trans_temperature_spin.setValue(trans_config.get("temperature", 0.3))
        self.trans_temperature_spin.setMaximumWidth(80)
        params_layout.addWidget(self.trans_temperature_spin)
        params_layout.addStretch()
        ai_layout.addLayout(params_layout)
        
        # 记忆最大条数和记忆时间在同一行
        memory_layout = QHBoxLayout()
        memory_layout.addWidget(QLabel("记忆最大条数:"))
        self.trans_memory_count_spin = QSpinBox()
        self.trans_memory_count_spin.setRange(1, 100)
        self.trans_memory_count_spin.setValue(trans_config.get("memory_max_count", 10))
        self.trans_memory_count_spin.setMaximumWidth(80)
        memory_layout.addWidget(self.trans_memory_count_spin)
        memory_layout.addWidget(QLabel("记忆时间 (秒):"))
        self.trans_memory_time_spin = QSpinBox()
        self.trans_memory_time_spin.setRange(10, 3600)
        self.trans_memory_time_spin.setValue(trans_config.get("memory_time", 300))
        self.trans_memory_time_spin.setMaximumWidth(100)
        memory_layout.addWidget(self.trans_memory_time_spin)
        memory_layout.addStretch()
        ai_layout.addLayout(memory_layout)
        
        ai_group.setLayout(ai_layout)
        
        # 下半部分：机器翻译设置
        machine_group = QGroupBox("机器翻译")
        machine_layout = QVBoxLayout(machine_group)
        
        # 提供商（只读，显示腾讯云）
        provider_layout = QHBoxLayout()
        provider_layout.addWidget(QLabel("提供商:"))
        self.machine_provider_label = QLabel("腾讯云")
        self.machine_provider_label.setStyleSheet("color: #888; font-style: italic;")
        provider_layout.addWidget(self.machine_provider_label)
        provider_layout.addStretch()
        machine_layout.addLayout(provider_layout)
        
        # SecretId和SecretKey在同一行
        secret_layout = QHBoxLayout()
        secret_layout.addWidget(QLabel("SecretId:"))
        self.tencent_secret_id_edit = QLineEdit()
        self.tencent_secret_id_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tencent_secret_id_edit.setText(machine_config.get("tencent_secret_id", ""))
        secret_layout.addWidget(self.tencent_secret_id_edit)
        secret_layout.addWidget(QLabel("SecretKey:"))
        self.tencent_secret_key_edit = QLineEdit()
        self.tencent_secret_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tencent_secret_key_edit.setText(machine_config.get("tencent_secret_key", ""))
        secret_layout.addWidget(self.tencent_secret_key_edit)
        secret_layout.addStretch()
        machine_layout.addLayout(secret_layout)
        
        # 服务器区域和目标语言在同一行
        region_lang_layout = QHBoxLayout()
        region_lang_layout.addWidget(QLabel("服务器区域:"))
        self.tencent_region_combo = QComboBox()
        regions = [
            ("亚太东南（曼谷）", "ap-bangkok"),
            ("华北地区（北京）", "ap-beijing"),
            ("西南地区（成都）", "ap-chengdu"),
            ("西南地区（重庆）", "ap-chongqing"),
            ("华南地区（广州）", "ap-guangzhou"),
            ("港澳台地区（中国香港）", "ap-hongkong"),
            ("亚太东北（首尔）", "ap-seoul"),
            ("华东地区（上海）", "ap-shanghai"),
            ("华东地区（上海金融）", "ap-shanghai-fsi"),
            ("华南地区（深圳金融）", "ap-shenzhen-fsi"),
            ("亚太东南（新加坡）", "ap-singapore"),
            ("亚太东北（东京）", "ap-tokyo"),
            ("欧洲地区（法兰克福）", "eu-frankfurt"),
            ("美国东部（弗吉尼亚）", "na-ashburn"),
            ("美国西部（硅谷）", "na-siliconvalley")
        ]
        for name, value in regions:
            self.tencent_region_combo.addItem(name, value)
        current_region = machine_config.get("tencent_region", "ap-beijing")
        for i in range(self.tencent_region_combo.count()):
            if self.tencent_region_combo.itemData(i) == current_region:
                self.tencent_region_combo.setCurrentIndex(i)
                break
        region_lang_layout.addWidget(self.tencent_region_combo)
        region_lang_layout.addWidget(QLabel("目标语言:"))
        self.tencent_target_lang_combo = QComboBox()
        self.tencent_target_lang_combo.addItems(["zh", "zh-TW", "en", "ja"])
        current_target_lang = machine_config.get("target_language", "zh")
        index = self.tencent_target_lang_combo.findText(current_target_lang)
        if index >= 0:
            self.tencent_target_lang_combo.setCurrentIndex(index)
        region_lang_layout.addWidget(self.tencent_target_lang_combo)
        region_lang_layout.addStretch()
        machine_layout.addLayout(region_lang_layout)
        
        # ProjectId和已消耗字符数在同一行
        project_chars_layout = QHBoxLayout()
        project_chars_layout.addWidget(QLabel("ProjectId:"))
        self.tencent_project_id_spin = QSpinBox()
        self.tencent_project_id_spin.setRange(0, 999999)
        self.tencent_project_id_spin.setValue(machine_config.get("project_id", 0))
        self.tencent_project_id_spin.setMaximumWidth(100)
        project_chars_layout.addWidget(self.tencent_project_id_spin)
        project_chars_layout.addWidget(QLabel("(一般无需填写)"))
        used_chars = machine_config.get("used_chars", 0)
        self.tencent_used_chars_label = QLabel()
        self._update_used_chars_display(used_chars)
        project_chars_layout.addWidget(QLabel("已消耗字符数:"))
        project_chars_layout.addWidget(self.tencent_used_chars_label)
        self.clear_chars_btn = QPushButton("清空计数")
        self.clear_chars_btn.setMaximumWidth(80)
        self.clear_chars_btn.clicked.connect(self._on_clear_chars_clicked)
        project_chars_layout.addWidget(self.clear_chars_btn)
        project_chars_layout.addStretch()
        machine_layout.addLayout(project_chars_layout)
        
        machine_group.setLayout(machine_layout)
        
        splitter.addWidget(ai_group)
        splitter.addWidget(machine_group)
        
        # 设置高度比例
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 200])
        
        layout.addWidget(splitter)
        group.setLayout(layout)
        return group
    
    def _update_used_chars_display(self, chars: int) -> None:
        """更新已消耗字符数显示"""
        if chars >= 1000000:
            # 超过1M，显示为X.XXm
            display = f"{chars / 1000000:.2f}m".rstrip('0').rstrip('.')
        elif chars >= 1000:
            # 超过1K，显示为X.XXk
            display = f"{chars / 1000:.2f}k".rstrip('0').rstrip('.')
        else:
            display = str(chars)
        self.tencent_used_chars_label.setText(display)
        self.tencent_used_chars_label.setStyleSheet("color: #4caf50; font-weight: bold;")
    
    def _on_used_chars_updated(self, chars: int) -> None:
        """更新已消耗字符数（通过信号调用）"""
        self._update_used_chars_display(chars)
    
    def _on_clear_chars_clicked(self) -> None:
        """清空字符计数按钮点击事件"""
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要清空已消耗字符数计数吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config.set("translation.machine_translation.used_chars", 0)
            self.config.save()
            self._update_used_chars_display(0)
            self.status_message_signal.emit("已清空字符计数", 2000)
    
    def _on_apply_settings_clicked(self) -> None:
        """应用设置按钮点击事件"""
        reply = QMessageBox.question(
            self,
            "确认",
            "应用设置后程序将重启，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.apply_settings_signal.emit()
    
    def _create_device_panel(self) -> QGroupBox:
        """创建音频设备选择面板"""
        from PyQt6.QtWidgets import QRadioButton
        
        group = QGroupBox("音频设备")
        layout = QVBoxLayout()
        
        # 第一行：输入设备
        input_device_layout = QHBoxLayout()
        self.input_device_radio = QRadioButton("输入设备:")
        self.input_device_radio.setChecked(True)  # 默认选择输入设备
        self.input_device_radio.toggled.connect(lambda checked: self._on_device_type_changed("input") if checked else None)
        input_device_layout.addWidget(self.input_device_radio)
        self.input_device_combo = QComboBox()
        self.input_device_combo.setMinimumWidth(300)
        self.input_device_combo.currentIndexChanged.connect(self._on_input_device_changed)
        input_device_layout.addWidget(self.input_device_combo)
        input_device_layout.addStretch()
        layout.addLayout(input_device_layout)
        
        # 第二行：桌面音频
        loopback_device_layout = QHBoxLayout()
        self.loopback_device_radio = QRadioButton("桌面音频:")
        self.loopback_device_radio.toggled.connect(lambda checked: self._on_device_type_changed("loopback") if checked else None)
        loopback_device_layout.addWidget(self.loopback_device_radio)
        self.loopback_device_combo = QComboBox()
        self.loopback_device_combo.setMinimumWidth(300)
        self.loopback_device_combo.currentIndexChanged.connect(self._on_loopback_device_changed)
        loopback_device_layout.addWidget(self.loopback_device_combo)
        loopback_device_layout.addStretch()
        layout.addLayout(loopback_device_layout)
        
        # 刷新按钮
        refresh_layout = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_devices_signal.emit)
        refresh_layout.addWidget(refresh_btn)
        refresh_layout.addStretch()
        layout.addLayout(refresh_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_listen_panel(self) -> QGroupBox:
        """创建监听控制面板"""
        group = QGroupBox("音频监听")
        layout = QVBoxLayout()
        
        # 第一行：监听按钮和音量显示
        control_layout = QHBoxLayout()
        self.listen_btn = QPushButton("开启监听")
        self.listen_btn.clicked.connect(self._on_listen_clicked)
        control_layout.addWidget(self.listen_btn)
        
        control_layout.addWidget(QLabel("实时音量:"))
        self.volume_bar = QProgressBar()
        self.volume_bar.setMinimum(0)
        self.volume_bar.setMaximum(100)
        self.volume_bar.setValue(0)
        self.volume_bar.setMinimumWidth(200)
        self.volume_bar.setFormat("%p%")
        control_layout.addWidget(self.volume_bar)
        
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # 第二行：音量阈值设置
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("音量阈值:"))
        self.volume_threshold_spin = QDoubleSpinBox()
        self.volume_threshold_spin.setRange(0.0, 100.0)
        self.volume_threshold_spin.setSingleStep(0.5)
        self.volume_threshold_spin.setValue(self.config.get("audio.volume_threshold", 1.0))
        self.volume_threshold_spin.setDecimals(1)
        self.volume_threshold_spin.setSuffix("%")
        self.volume_threshold_spin.valueChanged.connect(self._on_volume_threshold_changed)
        threshold_layout.addWidget(self.volume_threshold_spin)
        threshold_layout.addWidget(QLabel("(低于此值不传递给识别模型)"))
        threshold_layout.addStretch()
        layout.addLayout(threshold_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_model_panel(self) -> QGroupBox:
        """创建模型控制面板"""
        group = QGroupBox("语音识别模型")
        layout = QVBoxLayout()
        
        # 第一行：语言选择和加载按钮
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("选择模型:"))
        self.language_combo = QComboBox()
        # 不自动加载，只记录选择
        self.language_combo.currentIndexChanged.connect(self._on_language_selected)
        model_layout.addWidget(self.language_combo)
        
        self.load_model_btn = QPushButton("加载模型")
        self.load_model_btn.clicked.connect(self._on_load_model_clicked)
        model_layout.addWidget(self.load_model_btn)
        
        model_layout.addStretch()
        layout.addLayout(model_layout)
        
        # 第二行：当前加载的模型路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("当前模型:"))
        self.model_path_label = QLabel("未加载")
        self.model_path_label.setStyleSheet("color: #888; font-style: italic;")
        path_layout.addWidget(self.model_path_label)
        path_layout.addStretch()
        layout.addLayout(path_layout)
        
        group.setLayout(layout)
        
        # 在创建完所有UI元素后，再扫描模型
        self._scan_available_models()
        
        return group
    
    def _scan_available_models(self) -> None:
        """扫描models文件夹，找到所有有效的模型并更新下拉框"""
        from pathlib import Path
        
        # 在开始扫描之前，先断开信号连接，避免在clear()和addItem()时触发信号
        try:
            self.language_combo.currentIndexChanged.disconnect()
        except TypeError:
            # 如果信号未连接，忽略错误
            pass
        
        self.language_combo.clear()
        self.model_folders = []  # 存储模型文件夹名称
        
        # 获取models路径
        vosk_config = self.config.get_vosk_config()
        model_path = Path(vosk_config.get("model_path", "models"))
        
        if not model_path.exists():
            self.language_combo.addItem("未找到models文件夹", None)
            self.load_model_btn.setEnabled(False)
            # 重新连接信号
            self.language_combo.currentIndexChanged.connect(self._on_language_selected)
            return
        
        # 扫描所有目录，查找有效模型
        for item in model_path.iterdir():
            if item.is_dir():
                # 检查是否是有效的模型目录
                if (item / "am" / "final.mdl").exists() or \
                   (item / "conf" / "model.conf").exists():
                    # 直接使用文件夹名称作为显示文本
                    self.language_combo.addItem(item.name, item.name)
                    self.model_folders.append(item.name)
        
        # 如果没有找到任何模型
        if len(self.model_folders) == 0:
            self.language_combo.addItem("未找到有效模型", None)
            self.load_model_btn.setEnabled(False)
            # 重新连接信号
            self.language_combo.currentIndexChanged.connect(self._on_language_selected)
        else:
            self.load_model_btn.setEnabled(True)
            # 尝试选择之前选择的模型（如果有）
            saved_language = vosk_config.get("language", "")
            if saved_language:
                # 信号已经在方法开始时断开，这里不需要再次断开
                # 尝试找到匹配的模型
                found = False
                for i in range(self.language_combo.count()):
                    if self.language_combo.itemData(i) == saved_language:
                        self.language_combo.setCurrentIndex(i)
                        found = True
                        break
                
                # 重新连接信号
                # 注意：如果没找到匹配的模型，currentIndex仍然是0（第一个模型）
                # 重新连接信号时，如果currentIndex是0，可能会触发_on_language_selected
                # 但_on_language_selected中已经检查了：如果配置中的language已经是这个值，就不保存
                # 所以如果找不到匹配的模型，currentIndex是0（cn模型），而配置中是ja模型
                # 重新连接信号时可能会触发_on_language_selected，将配置改为cn模型
                # 为了安全起见，在重新连接信号之前，先检查当前索引对应的模型是否与保存的模型匹配
                current_index = self.language_combo.currentIndex()
                current_model = self.language_combo.itemData(current_index) if current_index >= 0 else None
                
                # 如果找到了匹配的模型，或者当前索引对应的模型与保存的模型匹配，才重新连接信号
                # 如果没找到匹配的模型，且当前索引对应的模型与保存的模型不匹配，说明配置中的模型不存在
                # 此时不应该重新连接信号，避免触发_on_language_selected覆盖配置
                if found or (current_model == saved_language):
                    self.language_combo.currentIndexChanged.connect(self._on_language_selected)
                else:
                    # 没找到匹配的模型，且当前索引对应的模型与保存的模型不匹配
                    # 不重新连接信号，避免触发_on_language_selected覆盖配置
                    # 但这样用户后续选择模型时不会保存，所以还是需要重新连接
                    # 使用blockSignals来临时阻止信号触发
                    self.language_combo.blockSignals(True)
                    self.language_combo.currentIndexChanged.connect(self._on_language_selected)
                    self.language_combo.blockSignals(False)
    
    def _create_recognition_control_panel(self) -> QGroupBox:
        """创建识别控制面板"""
        group = QGroupBox("语音识别")
        layout = QHBoxLayout()
        
        self.recognition_btn = QPushButton("开启识别")
        self.recognition_btn.clicked.connect(self._on_recognition_clicked)
        self.recognition_btn.setEnabled(False)  # 初始禁用，需要监听和模型都准备好
        layout.addWidget(self.recognition_btn)
        
        # 清空按钮移到开启识别按钮后面
        self.clear_texts_btn = QPushButton("清空")
        self.clear_texts_btn.clicked.connect(self._on_clear_texts_clicked)
        layout.addWidget(self.clear_texts_btn)
        
        layout.addStretch()
        
        group.setLayout(layout)
        return group
    
    def _create_translation_control_panel(self) -> QGroupBox:
        """创建翻译控制面板"""
        group = QGroupBox("翻译")
        layout = QVBoxLayout()
        
        # 第一行：翻译按钮、状态圆点和耗时统计
        control_layout = QHBoxLayout()
        self.translation_btn = QPushButton("开启翻译")
        self.translation_btn.clicked.connect(self._on_translation_clicked)
        self.translation_btn.setEnabled(False)  # 初始禁用，需要识别开启
        control_layout.addWidget(self.translation_btn)
        
        # 状态圆点
        self.translation_status_label = QLabel("●")
        self.translation_status_label.setStyleSheet("color: #888; font-size: 16px;")
        control_layout.addWidget(self.translation_status_label)
        
        # 耗时统计标签
        self.translation_time_label = QLabel("")
        self.translation_time_label.setStyleSheet("color: #888; font-size: 12px;")
        control_layout.addWidget(self.translation_time_label)
        
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # 第二行：即时翻译、AI翻译、即时翻译使用机翻勾选框
        instant_layout = QHBoxLayout()
        trans_config = self.config.get_translation_config()
        self.instant_translate_checkbox = QCheckBox("即时翻译")
        self.instant_translate_checkbox.setChecked(trans_config.get("instant_translate", False))
        self.instant_translate_checkbox.stateChanged.connect(self._on_instant_translate_changed)
        instant_layout.addWidget(self.instant_translate_checkbox)
        
        self.use_ai_translation_checkbox = QCheckBox("AI翻译")
        self.use_ai_translation_checkbox.setChecked(trans_config.get("use_ai_translation", True))
        self.use_ai_translation_checkbox.stateChanged.connect(self._on_use_ai_translation_changed)
        instant_layout.addWidget(self.use_ai_translation_checkbox)
        
        self.instant_use_machine_translation_checkbox = QCheckBox("即时翻译使用机翻")
        self.instant_use_machine_translation_checkbox.setChecked(trans_config.get("instant_use_machine_translation", True))
        self.instant_use_machine_translation_checkbox.stateChanged.connect(self._on_instant_use_machine_translation_changed)
        instant_layout.addWidget(self.instant_use_machine_translation_checkbox)
        
        instant_layout.addStretch()
        layout.addLayout(instant_layout)
        
        # 第三行：手动测试
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(QLabel("手动测试:"))
        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText("输入要翻译的文本...")
        self.manual_input.setMinimumWidth(200)
        manual_layout.addWidget(self.manual_input)
        
        self.test_translate_btn = QPushButton("测试翻译")
        self.test_translate_btn.clicked.connect(self._on_test_translate_clicked)
        manual_layout.addWidget(self.test_translate_btn)
        
        manual_layout.addStretch()
        layout.addLayout(manual_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_recognition_panel(self) -> QGroupBox:
        """创建识别文本面板"""
        group = QGroupBox("识别文本")
        layout = QVBoxLayout()
        
        self.recognition_text = QTextEdit()
        self.recognition_text.setReadOnly(True)
        self.recognition_text.setPlaceholderText("识别的文本将显示在这里...")
        font = QFont("Consolas", 12)
        self.recognition_text.setFont(font)
        layout.addWidget(self.recognition_text)
        
        group.setLayout(layout)
        return group
    

    
    def _create_config_panel(self) -> QGroupBox:
        """创建配置面板（可选，可通过菜单访问）"""
        group = QGroupBox("API配置")
        layout = QVBoxLayout()
        
        # API密钥
        layout.addWidget(QLabel("API密钥:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.api_key_edit)
        
        # API地址
        layout.addWidget(QLabel("API地址:"))
        self.api_url_edit = QLineEdit()
        layout.addWidget(self.api_url_edit)
        
        # 目标语言
        layout.addWidget(QLabel("目标语言:"))
        self.target_lang_combo = QComboBox()
        self.target_lang_combo.addItems(["中文", "英文", "日文", "韩文"])
        layout.addWidget(self.target_lang_combo)
        
        group.setLayout(layout)
        return group
    
    def _apply_style(self) -> None:
        """应用样式"""
        # 设置深色主题（补充QApplication级别的样式）
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #d4d4d4;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #2b2b2b;
                color: #d4d4d4;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #d4d4d4;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                selection-background-color: #0e639c;
                selection-color: white;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #0a4d73;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
            QComboBox {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                selection-background-color: #0e639c;
                selection-color: white;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #3c3c3c;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #d4d4d4;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                color: #d4d4d4;
                selection-background-color: #0e639c;
                selection-color: white;
                border: 1px solid #555;
            }
            QLineEdit {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                selection-background-color: #0e639c;
                selection-color: white;
            }
            QLabel {
                color: #d4d4d4;
                background-color: transparent;
            }
            QStatusBar {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border-top: 1px solid #555;
            }
            QProgressBar {
                background-color: #1e1e1e;
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                color: #d4d4d4;
            }
            QProgressBar::chunk {
                background-color: #0e639c;
                border-radius: 2px;
            }
            QCheckBox {
                color: #d4d4d4;
                background-color: transparent;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #3c3c3c;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #0e639c;
                border: 1px solid #0e639c;
            }
            QRadioButton {
                color: #d4d4d4;
                background-color: transparent;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 1px solid #555;
                background-color: #3c3c3c;
            }
            QRadioButton::indicator:checked {
                background-color: #0e639c;
                border: 1px solid #0e639c;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 3px;
                selection-background-color: #0e639c;
                selection-color: white;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                background-color: #555;
                border: none;
                border-top-left-radius: 3px;
                border-top-right-radius: 3px;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {
                background-color: #666;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                background-color: #555;
                border: none;
                border-bottom-left-radius: 3px;
                border-bottom-right-radius: 3px;
            }
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #666;
            }
        """)
    
    def apply_config(self) -> None:
        """应用配置"""
        # 应用翻译配置
        trans_config = self.config.get_translation_config()
        if hasattr(self, 'api_key_edit'):
            self.api_key_edit.setText(trans_config.get("api_key", ""))
        if hasattr(self, 'api_url_edit'):
            self.api_url_edit.setText(trans_config.get("api_url", ""))
    
    def _on_listen_clicked(self) -> None:
        """监听按钮点击事件"""
        if not hasattr(self, 'is_listening') or not self.is_listening:
            self.listen_start_signal.emit()
        else:
            self.listen_stop_signal.emit()
    
    def _on_language_selected(self, index: int) -> None:
        """模型选择改变事件（仅记录选择，不加载模型）"""
        model_folder = self.language_combo.itemData(index)
        if not model_folder:
            return
        
        # 检查是否是用户主动选择（而不是初始化时的设置）
        # 如果当前配置中的language已经是这个值，说明是初始化时设置的，不需要保存
        vosk_config = self.config.get_vosk_config()
        current_saved_language = vosk_config.get("language", "")
        if current_saved_language == model_folder:
            # 配置已经是这个值，可能是初始化时设置的，不需要重复保存
            return
        
        # 保存选择的模型文件夹名称
        vosk_config["language"] = model_folder
        self.config.set("vosk.language", model_folder)
        self.config.save()
        print(f"模型选择已保存: {model_folder}")
    
    def _on_load_model_clicked(self) -> None:
        """加载模型按钮点击事件"""
        self.load_model_signal.emit()
    
    def _on_recognition_clicked(self) -> None:
        """识别按钮点击事件"""
        if not hasattr(self, 'is_recognizing') or not self.is_recognizing:
            self.recognition_start_signal.emit()
        else:
            self.recognition_stop_signal.emit()
    
    def _on_translation_clicked(self) -> None:
        """翻译按钮点击事件"""
        if not hasattr(self, 'is_translating') or not self.is_translating:
            self.translation_start_signal.emit()
        else:
            self.translation_stop_signal.emit()
    
    def _on_test_translate_clicked(self) -> None:
        """测试翻译按钮点击事件"""
        text = self.manual_input.text().strip()
        if text:
            self.manual_translate_signal.emit(text)
        else:
            self.status_message_signal.emit("请输入要翻译的文本", 2000)
    
    def _on_clear_texts_clicked(self) -> None:
        """清空按钮点击事件"""
        self.clear_texts_signal.emit()
    
    def _on_instant_translate_changed(self, state: int) -> None:
        """即时翻译勾选框状态改变事件"""
        # 立即更新配置，使设置实时生效
        # QCheckBox.stateChanged 信号传递的是 Qt.CheckState 枚举值
        # Qt.CheckState.Checked = 2, Qt.CheckState.Unchecked = 0
        is_checked = (state == 2)  # Qt.CheckState.Checked
        self.config.set("translation.instant_translate", is_checked)
        self.config.save()
        # 发送信号通知主程序配置已更新
        self.instant_translate_changed_signal.emit(is_checked)
    
    def _on_use_ai_translation_changed(self, state: int) -> None:
        """AI翻译勾选框状态改变事件"""
        is_checked = (state == 2)
        self.config.set("translation.use_ai_translation", is_checked)
        self.config.save()
    
    def _on_instant_use_machine_translation_changed(self, state: int) -> None:
        """即时翻译使用机翻勾选框状态改变事件"""
        is_checked = (state == 2)
        self.config.set("translation.instant_use_machine_translation", is_checked)
        self.config.save()
    
    def show_status_message(self, message: str, timeout: int = 2000) -> None:
        """显示状态栏消息"""
        self.status_bar.showMessage(message, timeout)
    
    def _on_device_changed(self, index: int) -> None:
        """设备选择改变事件（已废弃，保留兼容性）"""
        device_index = self.device_combo.itemData(index)
        if device_index is not None:
            self.device_changed_signal.emit(device_index)
    
    def _on_input_device_changed(self, index: int) -> None:
        """输入设备选择改变事件"""
        device_index = self.input_device_combo.itemData(index)
        if device_index is not None:
            self.input_device_changed_signal.emit(device_index)
    
    def _on_loopback_device_changed(self, index: int) -> None:
        """桌面音频设备选择改变事件"""
        device_index = self.loopback_device_combo.itemData(index)
        if device_index is not None:
            self.loopback_device_changed_signal.emit(device_index)
    
    def _on_device_type_changed(self, device_type: str) -> None:
        """设备类型改变事件"""
        self.device_type_changed_signal.emit(device_type)
    
    def _on_volume_threshold_changed(self, value: float) -> None:
        """音量阈值改变事件"""
        self.volume_threshold_changed_signal.emit(value)
    
    def update_volume(self, volume: float) -> None:
        """
        更新音量显示
        
        Args:
            volume: 音量值（0-100）
        """
        self.volume_bar.setValue(int(volume))
        
        # 根据音量值设置颜色
        if volume > 80:
            color = "#f44336"  # 红色（过高）
        elif volume > 50:
            color = "#ff9800"  # 橙色（中等）
        elif volume > 20:
            color = "#4caf50"  # 绿色（正常）
        else:
            color = "#9e9e9e"  # 灰色（低）
        
        self.volume_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                background-color: #1e1e1e;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 2px;
            }}
        """)
    
    def update_device_list(self, input_devices: list, loopback_devices: list, 
                          default_input_index: Optional[int] = None,
                          default_loopback_index: Optional[int] = None,
                          device_type: str = "input") -> None:
        """
        更新设备列表
        
        Args:
            input_devices: 输入设备列表，每个设备是字典，包含index和name
            loopback_devices: 桌面音频设备列表，每个设备是字典，包含index和name
            default_input_index: 默认选择的输入设备索引
            default_loopback_index: 默认选择的桌面音频设备索引
            device_type: 当前设备类型 ("input" 或 "loopback")
        """
        # 更新输入设备列表
        self.input_device_combo.clear()
        self.input_device_indices = []
        
        for device in input_devices:
            device_idx = device.get('index')
            device_name = device.get('name', 'Unknown')
            is_cable = device.get('isCABLE', False)
            
            # 格式化显示名称
            display_name = f"[{device_idx}] {device_name}"
            if is_cable:
                display_name += " (CABLE)"
            
            self.input_device_combo.addItem(display_name, device_idx)
            self.input_device_indices.append(device_idx)
            
            # 如果是CABLE设备或默认设备，设置为当前选择
            if default_input_index is None and is_cable:
                default_input_index = device_idx
        
        # 设置输入设备默认选择
        if default_input_index is not None:
            try:
                idx = self.input_device_indices.index(default_input_index)
                self.input_device_combo.setCurrentIndex(idx)
            except ValueError:
                pass
        
        # 更新桌面音频设备列表
        self.loopback_device_combo.clear()
        self.loopback_device_indices = []
        
        for device in loopback_devices:
            device_idx = device.get('index')
            device_name = device.get('name', 'Unknown')
            
            # 格式化显示名称
            display_name = f"[{device_idx}] {device_name}"
            
            self.loopback_device_combo.addItem(display_name, device_idx)
            self.loopback_device_indices.append(device_idx)
        
        # 设置桌面音频设备默认选择
        if default_loopback_index is not None:
            try:
                idx = self.loopback_device_indices.index(default_loopback_index)
                self.loopback_device_combo.setCurrentIndex(idx)
            except ValueError:
                pass
        
        # 设置设备类型单选按钮
        if device_type == "input":
            self.input_device_radio.setChecked(True)
        else:
            self.loopback_device_radio.setChecked(True)
    
    def update_recognition_text(self, text: str, is_final: bool = False, speaker_id: Optional[int] = None, feature_hash: str = "") -> None:
        """
        更新识别文本（倒序显示，最新在上）
        
        Args:
            text: 识别文本
            is_final: 是否为最终结果
            speaker_id: 说话人ID（如果有多个说话人）
            feature_hash: 特征码字符串（已废弃，不再显示）
        """
        from datetime import datetime
        
        if is_final:
            # 最终结果：插入到顶部（倒序）
            current_time = datetime.now().strftime("%H:%M")
            
            # 如果有说话人ID，在时间戳后添加标识
            if speaker_id is not None:
                timestamped_text = f"[{current_time}]({speaker_id}) {text}"
            else:
                timestamped_text = f"[{current_time}] {text}"
            
            current_text = self.recognition_text.toPlainText()
            # 保存当前滚动条位置（顶部应该是0）
            scroll_pos = self.recognition_text.verticalScrollBar().value()
            
            if current_text:
                # 插入到顶部
                self.recognition_text.setPlainText(f"{timestamped_text}\n{current_text}")
            else:
                self.recognition_text.setText(timestamped_text)
            
            # 保持滚动条位置
            self.recognition_text.verticalScrollBar().setValue(scroll_pos)
        else:
            # 部分结果：更新第一行（最上面的行）
            current_text = self.recognition_text.toPlainText()
            lines = current_text.split('\n')
            
            # 保存当前滚动条位置
            scroll_pos = self.recognition_text.verticalScrollBar().value()
            
            if lines and lines[0].strip():
                # 检查第一行是否有时间戳，如果有则保留时间戳
                first_line = lines[0]
                if first_line.startswith('[') and ']' in first_line:
                    # 提取时间戳部分（可能包含说话人标识）
                    time_end = first_line.find(']')
                    # 检查是否有说话人标识
                    if time_end + 1 < len(first_line) and first_line[time_end + 1:time_end + 2] == '(':
                        # 有说话人标识，提取到')'为止
                        speaker_end = first_line.find(')', time_end + 1)
                        if speaker_end > 0:
                            timestamp = first_line[:speaker_end + 1]
                            lines[0] = f"{timestamp} {text}"
                        else:
                            timestamp = first_line[:time_end + 1]
                            if speaker_id is not None:
                                lines[0] = f"{timestamp}({speaker_id}) {text}"
                            else:
                                lines[0] = f"{timestamp} {text}"
                    else:
                        # 没有说话人标识
                        timestamp = first_line[:time_end + 1]
                        if speaker_id is not None:
                            lines[0] = f"{timestamp}({speaker_id}) {text}"
                        else:
                            lines[0] = f"{timestamp} {text}"
                else:
                    # 没有时间戳，添加新的时间戳
                    current_time = datetime.now().strftime("%H:%M")
                    if speaker_id is not None:
                        lines[0] = f"[{current_time}]({speaker_id}) {text}"
                    else:
                        lines[0] = f"[{current_time}] {text}"
            else:
                # 没有内容，创建新行
                current_time = datetime.now().strftime("%H:%M")
                if speaker_id is not None:
                    lines = [f"[{current_time}]({speaker_id}) {text}"]
                else:
                    lines = [f"[{current_time}] {text}"]
            
            self.recognition_text.setPlainText('\n'.join(lines))
            # 保持滚动条位置在顶部（0）
            self.recognition_text.verticalScrollBar().setValue(0)
    
    def update_translation_text(self, text: str, speaker_id: Optional[int] = None) -> None:
        """
        更新翻译文本（完整句子，更新最近和历史，倒序显示，最新在上）
        
        Args:
            text: 翻译文本
            speaker_id: 说话人ID（如果有多个说话人）
        """
        import re
        from datetime import datetime
        
        # 移除权重前缀（格式：数字+|分隔符，例如 "85|这是翻译结果"）
        cleaned_text = text
        weight_match = re.match(r'^(\d{1,2})\|', text.strip())
        if weight_match:
            # 移除权重前缀，只保留翻译结果
            cleaned_text = text[weight_match.end():].strip()
        
        # 更新最近一次翻译
        self.translation_latest_text.setText(cleaned_text)
        
        # 更新翻译历史（插入到顶部，倒序）
        current_time = datetime.now().strftime("%H:%M")
        # 如果有说话人ID，在时间戳后添加标识
        if speaker_id is not None:
            timestamped_text = f"[{current_time}]({speaker_id}) {cleaned_text}"
        else:
            timestamped_text = f"[{current_time}] {cleaned_text}"
        
        current_history = self.translation_history_text.toPlainText()
        # 保存当前滚动条位置（顶部应该是0）
        scroll_pos = self.translation_history_text.verticalScrollBar().value()
        
        if current_history:
            # 插入到顶部
            self.translation_history_text.setPlainText(f"{timestamped_text}\n{current_history}")
        else:
            self.translation_history_text.setText(timestamped_text)
        
        # 保持滚动条位置在顶部（0）
        self.translation_history_text.verticalScrollBar().setValue(0)
    
    def update_translation_latest_text_only(self, text: str, speaker_id: Optional[int] = None) -> None:
        """
        只更新最近一次翻译文本（即时翻译用，不更新历史）
        
        Args:
            text: 翻译文本
            speaker_id: 说话人ID（如果有多个说话人）
        """
        import re
        
        # 移除权重前缀（格式：数字+|分隔符，例如 "85|这是翻译结果"）
        cleaned_text = text
        weight_match = re.match(r'^(\d{1,2})\|', text.strip())
        if weight_match:
            # 移除权重前缀，只保留翻译结果
            cleaned_text = text[weight_match.end():].strip()
        
        # 如果有说话人ID，在文本前添加标识（用于显示）
        if speaker_id is not None:
            display_text = f"({speaker_id}) {cleaned_text}"
        else:
            display_text = cleaned_text
        
        # 只更新最近一次翻译，不更新历史
        self.translation_latest_text.setText(display_text)
    
    def clear_all_texts(self) -> None:
        """清空所有文本显示"""
        self.recognition_text.clear()
        self.translation_latest_text.clear()
        self.translation_history_text.clear()
    
    def clear_recognition_text(self) -> None:
        """只清空识别文本"""
        self.recognition_text.clear()
    
    def clear_translation_texts(self) -> None:
        """只清空翻译文本（最近翻译和历史翻译）"""
        self.translation_latest_text.clear()
        self.translation_history_text.clear()
    
    def update_recognition_text_for_test(self, text: str) -> None:
        """
        为测试更新识别文本（模拟识别结果，倒序显示，最新在上）
        
        Args:
            text: 识别文本
        """
        from datetime import datetime
        
        current_time = datetime.now().strftime("%H:%M")
        timestamped_text = f"[{current_time}] {text}"
        
        current_text = self.recognition_text.toPlainText()
        # 保存当前滚动条位置（顶部应该是0）
        scroll_pos = self.recognition_text.verticalScrollBar().value()
        
        if current_text:
            # 插入到顶部（倒序）
            self.recognition_text.setPlainText(f"{timestamped_text}\n{current_text}")
        else:
            self.recognition_text.setText(timestamped_text)
        
        # 保持滚动条位置
        self.recognition_text.verticalScrollBar().setValue(scroll_pos)
    
    def set_listening_state(self, listening: bool) -> None:
        """设置监听状态"""
        self.is_listening = listening
        if listening:
            self.listen_btn.setText("关闭监听")
            self.listen_btn.setStyleSheet("""
                QPushButton {
                    background-color: #c72222;
                }
                QPushButton:hover {
                    background-color: #e02424;
                }
            """)
        else:
            self.listen_btn.setText("开启监听")
            self.listen_btn.setStyleSheet("")
            # 关闭监听时，也关闭识别和翻译
            if self.is_recognizing:
                self.set_recognition_state(False)
            if self.is_translating:
                self.set_translation_state(False)
        # 更新识别按钮状态
        self._update_recognition_button_state()
    
    def set_model_loaded(self, model_path: str) -> None:
        """设置模型已加载"""
        self.model_path_label.setText(model_path if model_path else "未加载")
        self.model_path_label.setStyleSheet("color: #4caf50; font-style: normal;")
        self.load_model_btn.setText("重载模型")
        # 检查是否可以启用识别按钮
        self._update_recognition_button_state()
    
    def set_recognition_state(self, recognizing: bool) -> None:
        """设置识别状态"""
        self.is_recognizing = recognizing
        if recognizing:
            self.recognition_btn.setText("关闭识别")
            self.recognition_btn.setStyleSheet("""
                QPushButton {
                    background-color: #c72222;
                }
                QPushButton:hover {
                    background-color: #e02424;
                }
            """)
        else:
            self.recognition_btn.setText("开启识别")
            self.recognition_btn.setStyleSheet("")
            # 关闭识别时，也关闭翻译
            if self.is_translating:
                self.set_translation_state(False)
        # 更新翻译按钮状态
        self._update_translation_button_state()
    
    def set_translation_state(self, translating: bool) -> None:
        """设置翻译状态"""
        self.is_translating = translating
        if translating:
            self.translation_btn.setText("关闭翻译")
            self.translation_btn.setStyleSheet("""
                QPushButton {
                    background-color: #c72222;
                }
                QPushButton:hover {
                    background-color: #e02424;
                }
            """)
        else:
            self.translation_btn.setText("开启翻译")
            self.translation_btn.setStyleSheet("")
    
    def update_translation_status(self, is_translating: bool, is_waiting: bool, translate_times: list) -> None:
        """
        更新翻译状态显示（圆点和耗时统计）
        
        Args:
            is_translating: 是否正在翻译
            is_waiting: 是否正在等待服务器返回
            translate_times: 最近20次翻译请求的耗时列表
        """
        if not is_translating:
            # 灰色：未启动翻译
            self.translation_status_label.setStyleSheet("color: #888; font-size: 28px;")
            self.translation_time_label.setText("")
        elif is_waiting:
            # 黄色：有正在等待服务器返回的翻译请求
            self.translation_status_label.setStyleSheet("color: #ff9800; font-size: 28px;")
            # 计算并显示耗时统计
            if translate_times:
                avg_time = sum(translate_times) / len(translate_times)
                max_time = max(translate_times)
                self.translation_time_label.setText(f"平均耗时({avg_time:.1f}秒) 最大耗时({max_time:.1f}秒)")
            else:
                self.translation_time_label.setText("")
        else:
            # 绿色：当前没有任何翻译请求
            self.translation_status_label.setStyleSheet("color: #4caf50; font-size: 28px;")
            # 计算并显示耗时统计
            if translate_times:
                avg_time = sum(translate_times) / len(translate_times)
                max_time = max(translate_times)
                self.translation_time_label.setText(f"平均耗时({avg_time:.1f}秒) 最大耗时({max_time:.1f}秒)")
            else:
                self.translation_time_label.setText("")
    
    def _update_recognition_button_state(self) -> None:
        """更新识别按钮的启用状态"""
        # 需要监听开启且模型已加载
        can_enable = self.is_listening and self.model_path_label.text() != "未加载"
        self.recognition_btn.setEnabled(can_enable)
    
    def _update_translation_button_state(self) -> None:
        """更新翻译按钮的启用状态"""
        # 需要识别开启
        self.translation_btn.setEnabled(self.is_recognizing)
    
    def show_error(self, title: str, message: str) -> None:
        """
        显示错误消息
        
        Args:
            title: 标题
            message: 消息
        """
        QMessageBox.critical(self, title, message)
    
    def show_info(self, title: str, message: str) -> None:
        """
        显示信息消息
        
        Args:
            title: 标题
            message: 消息
        """
        QMessageBox.information(self, title, message)
    
    def get_api_config(self) -> dict:
        """
        获取API配置
        
        Returns:
            配置字典
        """
        config = {}
        if hasattr(self, 'trans_api_key_edit'):
            config['api_key'] = self.trans_api_key_edit.text()
        if hasattr(self, 'trans_api_url_edit'):
            config['api_url'] = self.trans_api_url_edit.text()
        if hasattr(self, 'trans_model_edit'):
            config['model'] = self.trans_model_edit.text()
        return config


    def _create_translation_panel(self) -> QGroupBox:
        """创建翻译结果面板（上下两个文本框，高度1:2）"""
        group = QGroupBox("翻译结果")
        layout = QVBoxLayout()
        
        # 使用分割器实现上下布局
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 上半部分：最近一次翻译
        latest_group = QGroupBox("最近一次翻译")
        latest_layout = QVBoxLayout(latest_group)
        self.translation_latest_text = QTextEdit()
        self.translation_latest_text.setReadOnly(True)
        self.translation_latest_text.setPlaceholderText("最近一次翻译结果将显示在这里...")
        font = QFont("Consolas", 12)
        self.translation_latest_text.setFont(font)
        latest_layout.addWidget(self.translation_latest_text)
        latest_group.setLayout(latest_layout)
        
        # 下半部分：翻译历史
        history_group = QGroupBox("翻译历史")
        history_layout = QVBoxLayout(history_group)
        self.translation_history_text = QTextEdit()
        self.translation_history_text.setReadOnly(True)
        self.translation_history_text.setPlaceholderText("翻译历史将显示在这里...")
        self.translation_history_text.setFont(font)
        history_layout.addWidget(self.translation_history_text)
        history_group.setLayout(history_layout)
        
        splitter.addWidget(latest_group)
        splitter.addWidget(history_group)
        
        # 设置高度比例 1:2
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([100, 200])
        
        layout.addWidget(splitter)
        group.setLayout(layout)
        return group