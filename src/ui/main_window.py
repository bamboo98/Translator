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
from typing import Optional, Callable
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
    device_changed_signal = pyqtSignal(int)  # 设备索引
    refresh_devices_signal = pyqtSignal()  # 刷新设备列表
    volume_updated_signal = pyqtSignal(float)  # 音量更新信号
    recognition_text_updated_signal = pyqtSignal(str, bool)  # 识别文本更新信号 (text, is_final)
    translation_text_updated_signal = pyqtSignal(str)  # 翻译文本更新信号（完整句子，更新最近和历史）
    translation_latest_text_updated_signal = pyqtSignal(str)  # 即时翻译文本更新信号（只更新最近）
    instant_translate_changed_signal = pyqtSignal(bool)  # 即时翻译设置改变信号
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
        group = QGroupBox("音频设置")
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
        
        # 块大小
        chunk_layout = QHBoxLayout()
        chunk_layout.addWidget(QLabel("块大小:"))
        self.audio_chunk_size_spin = QSpinBox()
        self.audio_chunk_size_spin.setRange(256, 8192)
        self.audio_chunk_size_spin.setValue(audio_config.get("chunk_size", 1024))
        chunk_layout.addWidget(self.audio_chunk_size_spin)
        chunk_layout.addStretch()
        layout.addLayout(chunk_layout)
        
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
        
        # API提供商
        provider_layout = QHBoxLayout()
        provider_layout.addWidget(QLabel("API提供商:"))
        self.trans_provider_combo = QComboBox()
        self.trans_provider_combo.addItems(["siliconflow", "openai", "custom"])
        current_provider = trans_config.get("api_provider", "siliconflow")
        index = self.trans_provider_combo.findText(current_provider)
        if index >= 0:
            self.trans_provider_combo.setCurrentIndex(index)
        provider_layout.addWidget(self.trans_provider_combo)
        provider_layout.addStretch()
        layout.addLayout(provider_layout)
        
        # API密钥
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("API密钥:"))
        self.trans_api_key_edit = QLineEdit()
        self.trans_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.trans_api_key_edit.setText(trans_config.get("api_key", ""))
        key_layout.addWidget(self.trans_api_key_edit)
        layout.addLayout(key_layout)
        
        # API地址
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("API地址:"))
        self.trans_api_url_edit = QLineEdit()
        self.trans_api_url_edit.setText(trans_config.get("api_url", ""))
        url_layout.addWidget(self.trans_api_url_edit)
        layout.addLayout(url_layout)
        
        # 模型名称
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("模型名称:"))
        self.trans_model_edit = QLineEdit()
        self.trans_model_edit.setText(trans_config.get("model", "deepseek-ai/DeepSeek-V3"))
        model_layout.addWidget(self.trans_model_edit)
        layout.addLayout(model_layout)
        
        # 超时时间
        timeout_layout = QHBoxLayout()
        timeout_layout.addWidget(QLabel("超时时间 (秒):"))
        self.trans_timeout_spin = QSpinBox()
        self.trans_timeout_spin.setRange(5, 300)
        self.trans_timeout_spin.setValue(trans_config.get("timeout", 30))
        timeout_layout.addWidget(self.trans_timeout_spin)
        timeout_layout.addStretch()
        layout.addLayout(timeout_layout)
        
        # Max Tokens
        max_tokens_layout = QHBoxLayout()
        max_tokens_layout.addWidget(QLabel("最大Token数:"))
        self.trans_max_tokens_spin = QSpinBox()
        self.trans_max_tokens_spin.setRange(100, 32000)
        self.trans_max_tokens_spin.setValue(trans_config.get("max_tokens", 8000))
        max_tokens_layout.addWidget(self.trans_max_tokens_spin)
        max_tokens_layout.addStretch()
        layout.addLayout(max_tokens_layout)
        
        # Temperature
        temperature_layout = QHBoxLayout()
        temperature_layout.addWidget(QLabel("Temperature:"))
        self.trans_temperature_spin = QDoubleSpinBox()
        self.trans_temperature_spin.setRange(0.0, 2.0)
        self.trans_temperature_spin.setSingleStep(0.1)
        self.trans_temperature_spin.setDecimals(1)
        self.trans_temperature_spin.setValue(trans_config.get("temperature", 0.3))
        temperature_layout.addWidget(self.trans_temperature_spin)
        temperature_layout.addStretch()
        layout.addLayout(temperature_layout)
        
        # 记忆最大条数
        memory_count_layout = QHBoxLayout()
        memory_count_layout.addWidget(QLabel("记忆最大条数:"))
        self.trans_memory_count_spin = QSpinBox()
        self.trans_memory_count_spin.setRange(1, 100)
        self.trans_memory_count_spin.setValue(trans_config.get("memory_max_count", 10))
        memory_count_layout.addWidget(self.trans_memory_count_spin)
        memory_count_layout.addStretch()
        layout.addLayout(memory_count_layout)
        
        # 记忆时间
        memory_time_layout = QHBoxLayout()
        memory_time_layout.addWidget(QLabel("记忆时间 (秒):"))
        self.trans_memory_time_spin = QSpinBox()
        self.trans_memory_time_spin.setRange(10, 3600)
        self.trans_memory_time_spin.setValue(trans_config.get("memory_time", 300))
        memory_time_layout.addWidget(self.trans_memory_time_spin)
        memory_time_layout.addStretch()
        layout.addLayout(memory_time_layout)
        
        group.setLayout(layout)
        return group
    
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
        group = QGroupBox("音频设备")
        layout = QVBoxLayout()
        
        # 设备选择下拉菜单
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("输入设备:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        device_layout.addWidget(self.device_combo)
        
        # 刷新按钮
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_devices_signal.emit)
        device_layout.addWidget(refresh_btn)
        
        device_layout.addStretch()
        layout.addLayout(device_layout)
        
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
        
        self.language_combo.clear()
        self.model_folders = []  # 存储模型文件夹名称
        
        # 获取models路径
        vosk_config = self.config.get_vosk_config()
        model_path = Path(vosk_config.get("model_path", "models"))
        
        if not model_path.exists():
            self.language_combo.addItem("未找到models文件夹", None)
            self.load_model_btn.setEnabled(False)
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
        else:
            self.load_model_btn.setEnabled(True)
            # 尝试选择之前选择的模型（如果有）
            saved_language = vosk_config.get("language", "")
            if saved_language:
                # 尝试找到匹配的模型
                for i in range(self.language_combo.count()):
                    if self.language_combo.itemData(i) == saved_language:
                        self.language_combo.setCurrentIndex(i)
                        break
    
    def _create_recognition_control_panel(self) -> QGroupBox:
        """创建识别控制面板"""
        group = QGroupBox("语音识别")
        layout = QHBoxLayout()
        
        self.recognition_btn = QPushButton("开启识别")
        self.recognition_btn.clicked.connect(self._on_recognition_clicked)
        self.recognition_btn.setEnabled(False)  # 初始禁用，需要监听和模型都准备好
        layout.addWidget(self.recognition_btn)
        
        layout.addStretch()
        
        group.setLayout(layout)
        return group
    
    def _create_translation_control_panel(self) -> QGroupBox:
        """创建翻译控制面板"""
        group = QGroupBox("翻译")
        layout = QVBoxLayout()
        
        # 第一行：翻译按钮和手动输入
        control_layout = QHBoxLayout()
        self.translation_btn = QPushButton("开启翻译")
        self.translation_btn.clicked.connect(self._on_translation_clicked)
        self.translation_btn.setEnabled(False)  # 初始禁用，需要识别开启
        control_layout.addWidget(self.translation_btn)
        
        control_layout.addWidget(QLabel("手动测试:"))
        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText("输入要翻译的文本...")
        self.manual_input.setMinimumWidth(200)
        control_layout.addWidget(self.manual_input)
        
        self.test_translate_btn = QPushButton("测试翻译")
        self.test_translate_btn.clicked.connect(self._on_test_translate_clicked)
        control_layout.addWidget(self.test_translate_btn)
        
        self.clear_texts_btn = QPushButton("清空")
        self.clear_texts_btn.clicked.connect(self._on_clear_texts_clicked)
        control_layout.addWidget(self.clear_texts_btn)
        
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # 第二行：即时翻译勾选框
        instant_layout = QHBoxLayout()
        trans_config = self.config.get_translation_config()
        self.instant_translate_checkbox = QCheckBox("即时翻译")
        self.instant_translate_checkbox.setChecked(trans_config.get("instant_translate", False))
        self.instant_translate_checkbox.stateChanged.connect(self._on_instant_translate_changed)
        instant_layout.addWidget(self.instant_translate_checkbox)
        instant_layout.addStretch()
        layout.addLayout(instant_layout)
        
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
        # 设置深色主题
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
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
            QComboBox, QLineEdit {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
            QLabel {
                color: #d4d4d4;
            }
            QStatusBar {
                background-color: #1e1e1e;
                color: #d4d4d4;
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
        if model_folder:
            # 保存选择的模型文件夹名称
            vosk_config = self.config.get_vosk_config()
            vosk_config["language"] = model_folder
            self.config.set("vosk.language", model_folder)
            self.config.save()
    
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
    
    def show_status_message(self, message: str, timeout: int = 2000) -> None:
        """显示状态栏消息"""
        self.status_bar.showMessage(message, timeout)
    
    def _on_device_changed(self, index: int) -> None:
        """设备选择改变事件"""
        device_index = self.device_combo.itemData(index)
        if device_index is not None:
            self.device_changed_signal.emit(device_index)
    
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
    
    def update_device_list(self, devices: list, default_index: Optional[int] = None) -> None:
        """
        更新设备列表
        
        Args:
            devices: 设备列表，每个设备是字典，包含index和name
            default_index: 默认选择的设备索引
        """
        self.device_combo.clear()
        self.device_indices = []
        
        for device in devices:
            device_idx = device.get('index')
            device_name = device.get('name', 'Unknown')
            is_cable = device.get('isCABLE', False)
            
            # 格式化显示名称
            display_name = f"[{device_idx}] {device_name}"
            if is_cable:
                display_name += " (CABLE)"
            
            self.device_combo.addItem(display_name, device_idx)
            self.device_indices.append(device_idx)
            
            # 如果是CABLE设备或默认设备，设置为当前选择
            if default_index is None and is_cable:
                default_index = device_idx
        
        # 设置默认选择
        if default_index is not None:
            try:
                idx = self.device_indices.index(default_index)
                self.device_combo.setCurrentIndex(idx)
            except ValueError:
                if self.device_combo.count() > 0:
                    self.device_combo.setCurrentIndex(0)
    
    def update_recognition_text(self, text: str, is_final: bool = False) -> None:
        """
        更新识别文本
        
        Args:
            text: 识别文本
            is_final: 是否为最终结果
        """
        if is_final:
            # 最终结果：追加新行
            current_text = self.recognition_text.toPlainText()
            if current_text:
                self.recognition_text.append(f"\n{text}")
            else:
                self.recognition_text.setText(text)
            # 滚动到底部
            self.recognition_text.verticalScrollBar().setValue(
                self.recognition_text.verticalScrollBar().maximum()
            )
        else:
            # 部分结果：更新最后一行
            current_text = self.recognition_text.toPlainText()
            lines = current_text.split('\n')
            if lines and not lines[-1].strip():
                lines.pop()
            if lines:
                lines[-1] = text
            else:
                lines = [text]
            self.recognition_text.setText('\n'.join(lines))
            # 滚动到底部
            self.recognition_text.verticalScrollBar().setValue(
                self.recognition_text.verticalScrollBar().maximum()
            )
    
    def update_translation_text(self, text: str) -> None:
        """
        更新翻译文本（完整句子，更新最近和历史）
        
        Args:
            text: 翻译文本
        """
        import re
        
        # 移除权重前缀（格式：数字+|分隔符，例如 "85|这是翻译结果"）
        cleaned_text = text
        weight_match = re.match(r'^(\d{1,2})\|', text.strip())
        if weight_match:
            # 移除权重前缀，只保留翻译结果
            cleaned_text = text[weight_match.end():].strip()
        
        # 更新最近一次翻译
        self.translation_latest_text.setText(cleaned_text)
        
        # 更新翻译历史（追加到历史记录）
        current_history = self.translation_history_text.toPlainText()
        if current_history:
            self.translation_history_text.append(f"\n{cleaned_text}")
        else:
            self.translation_history_text.setText(cleaned_text)
        # 滚动到底部
        self.translation_history_text.verticalScrollBar().setValue(
            self.translation_history_text.verticalScrollBar().maximum()
        )
    
    def update_translation_latest_text_only(self, text: str) -> None:
        """
        只更新最近一次翻译文本（即时翻译用，不更新历史）
        
        Args:
            text: 翻译文本
        """
        import re
        
        # 移除权重前缀（格式：数字+|分隔符，例如 "85|这是翻译结果"）
        cleaned_text = text
        weight_match = re.match(r'^(\d{1,2})\|', text.strip())
        if weight_match:
            # 移除权重前缀，只保留翻译结果
            cleaned_text = text[weight_match.end():].strip()
        
        # 只更新最近一次翻译，不更新历史
        self.translation_latest_text.setText(cleaned_text)
    
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
        为测试更新识别文本（模拟识别结果）
        
        Args:
            text: 识别文本
        """
        current_text = self.recognition_text.toPlainText()
        if current_text:
            self.recognition_text.append(f"\n{text}")
        else:
            self.recognition_text.setText(text)
        # 滚动到底部
        self.recognition_text.verticalScrollBar().setValue(
            self.recognition_text.verticalScrollBar().maximum()
        )
    
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