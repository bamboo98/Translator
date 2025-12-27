"""
桌面音频捕获和语音识别测试程序
使用 PyQt6 窗口显示，捕获桌面音频并使用 Vosk 进行语音识别
"""
import sys
import json
import threading
import queue
from pathlib import Path
import pyaudiowpatch
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QLabel, QTextEdit, QPushButton, QStatusBar, QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from vosk import Model, KaldiRecognizer


class AudioCaptureThread(QObject):
    """音频捕获线程 - 使用分块累积处理"""
    audio_data_signal = pyqtSignal(bytes)  # 发送音频数据信号
    volume_updated_signal = pyqtSignal(float)  # 发送音量更新信号
    device_name_updated_signal = pyqtSignal(str)  # 发送设备名称更新信号
    
    def __init__(self, device_index=None, process_interval_seconds=3.0):
        """
        初始化音频捕获线程
        
        Args:
            device_index: 设备索引，None表示使用默认设备
            process_interval_seconds: 处理间隔（秒），默认3秒
        """
        super().__init__()
        self.pa = None
        self.device_index = device_index
        self.audio_stream = None
        self.running = False
        self.device_name = ""
        self.sample_rate = 16000  # 目标采样率（用于Vosk）
        self.process_interval_seconds = process_interval_seconds  # 处理间隔（秒）
        self.thread = None
        
        # 实际使用的采样率（可能与目标采样率不同）
        self.actual_sample_rate = self.sample_rate
        
        # 分块累积处理相关（将在start_capture中根据实际采样率计算）
        self.chunk_size = None  # 每次读取的帧数（根据采样率自动计算）
        self.process_interval = None  # 需要累积多少帧后处理一次
        self.frames = []  # 累积的音频帧
        self.frame_count = 0
        self.frame_volumes = []  # 累积的音量值
        
    def list_devices(self):
        """列出所有可用的环回设备"""
        devices = []
        try:
            if self.pa is None:
                self.pa = pyaudiowpatch.PyAudio()
            for device in self.pa.get_loopback_device_info_generator():
                devices.append({
                    "index": device["index"],
                    "name": device["name"],
                    "sample_rate": device["defaultSampleRate"],
                    "channels": device["maxInputChannels"]
                })
        except Exception as e:
            print(f"枚举设备失败: {e}")
        return devices
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio回调函数 - 分块累积处理"""
        if status:
            print(f"音频捕获状态: {status}")
        
        # 处理音频数据：转换为numpy数组（float32格式）
        samples = np.frombuffer(in_data, dtype=np.float32)
        
        # 计算当前音频块的音量（用于显示和过滤）
        rms = np.sqrt(np.mean(samples ** 2))
        peak = np.max(np.abs(samples))
        # 转换为0-100的百分比（线性）
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
        
        # 发送实时音量更新信号（用于UI显示）
        self.volume_updated_signal.emit(volume)
        
        # 转换为 int16 格式（用于累积和识别）
        # float32 范围是 -1.0 到 1.0，需要缩放到 int16 范围
        samples_int16 = (samples * 32767).astype(np.int16)
        audio_data = samples_int16.tobytes()
        
        # 累积音频帧和音量
        self.frames.append(audio_data)
        self.frame_count += 1
        self.frame_volumes.append(volume)
        
        # 达到处理间隔时处理累积的音频块
        if len(self.frames) >= self.process_interval:
            # 合并所有累积的帧
            audio_bytes = b''.join(self.frames)
            
            # 计算累积块的平均音量
            avg_volume = 0.0
            if self.frame_volumes:
                avg_volume = sum(self.frame_volumes) / len(self.frame_volumes)
            
            # 清空累积的帧和音量
            self.frames = []
            self.frame_count = 0
            self.frame_volumes = []
            
            # 如果平均音量 <= 1%，不传递给识别模型
            if avg_volume <= 1.0:
                return (None, pyaudiowpatch.paContinue)
            
            # 如果实际采样率与目标采样率不同，进行重采样
            if self.actual_sample_rate != self.sample_rate:
                try:
                    # 转换为numpy数组
                    audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                    # 重采样到目标采样率
                    ratio = self.sample_rate / self.actual_sample_rate
                    original_length = len(audio_array)
                    target_length = int(original_length * ratio)
                    indices = np.linspace(0, original_length - 1, target_length)
                    resampled_array = np.interp(indices, np.arange(original_length), audio_array)
                    # 转换回int16并转为字节
                    audio_bytes = resampled_array.astype(np.int16).tobytes()
                except Exception as e:
                    print(f"重采样失败: {e}，使用原始音频")
            
            # 发送累积的音频数据信号
            self.audio_data_signal.emit(audio_bytes)
        
        return (None, pyaudiowpatch.paContinue)
    
    def start_capture(self):
        """开始捕获音频（在线程中运行）"""
        try:
            if self.pa is None:
                self.pa = pyaudiowpatch.PyAudio()
            
            # 获取设备信息
            if self.device_index is None:
                device_info = self.pa.get_default_wasapi_loopback()
            else:
                device_info = self.pa.get_device_info_by_index(self.device_index)
            
            self.device_name = device_info["name"]
            original_sample_rate = int(device_info["defaultSampleRate"])
            self.actual_sample_rate = original_sample_rate
            
            # 根据采样率自动计算chunk_size（每次读取约0.1秒的数据）
            # 这样可以保证回调频率适中，不会太频繁也不会太慢
            self.chunk_size = int(original_sample_rate * 0.1)
            # 确保chunk_size在合理范围内（最小1024，最大8192）
            self.chunk_size = max(1024, min(8192, self.chunk_size))
            
            # 根据处理间隔秒数和采样率计算需要累积多少帧
            # 例如：48000Hz * 3秒 = 144000帧，需要累积这么多帧后处理一次
            total_frames_for_interval = int(self.actual_sample_rate * self.process_interval_seconds)
            self.process_interval = total_frames_for_interval // self.chunk_size
            # 确保至少累积1帧
            if self.process_interval < 1:
                self.process_interval = 1
            
            print(f"使用设备: {self.device_name}")
            print(f"原始采样率: {original_sample_rate}Hz")
            print(f"目标采样率: {self.sample_rate}Hz")
            print(f"处理间隔配置: {self.process_interval_seconds}秒")
            print(f"Chunk大小: {self.chunk_size} 帧（约{self.chunk_size/original_sample_rate:.3f}秒）")
            print(f"处理间隔: 每{self.process_interval}个chunk（约{self.process_interval * self.chunk_size / original_sample_rate:.2f}秒）处理一次")
            
            # 打开音频流（使用原始采样率和回调函数）
            self.audio_stream = self.pa.open(
                rate=original_sample_rate,
                channels=1,
                format=pyaudiowpatch.paFloat32,
                input=True,
                input_device_index=device_info["index"],
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback,
                start=False
            )
            
            # 重置累积帧和音量
            self.frames = []
            self.frame_count = 0
            self.frame_volumes = []
            
            # 发送设备名称更新信号
            if self.device_name:
                self.device_name_updated_signal.emit(self.device_name)
            
            # 启动流
            self.audio_stream.start_stream()
            self.running = True
            
            print(f"音频捕获已启动: {self.device_name}")
            print(f"  - 捕获配置: 1声道, {self.actual_sample_rate}Hz, float32")
            print(f"  - 目标配置: 1声道, {self.sample_rate}Hz, int16 (用于Vosk)")
            if self.actual_sample_rate != self.sample_rate:
                print(f"  - 将自动进行重采样")
            
            # 保持线程运行
            while self.running:
                import time
                time.sleep(0.1)
                    
        except Exception as e:
            print(f"捕获错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop_capture()
    
    def stop_capture(self):
        """停止捕获并清理资源"""
        self.running = False
        if self.audio_stream:
            try:
                if not self.audio_stream.is_stopped():
                    self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
            except Exception as e:
                print(f"关闭音频流错误: {e}")
        
        # 清空累积的帧和音量
        self.frames = []
        self.frame_count = 0
        self.frame_volumes = []
        
        if self.pa:
            try:
                self.pa.terminate()
                self.pa = None
            except Exception as e:
                print(f"终止PyAudio错误: {e}")
        print("音频捕获已停止")
    
    def start(self):
        """启动捕获线程"""
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.start_capture, daemon=True)
            self.thread.start()


class VoskRecognizer(QObject):
    """Vosk 语音识别器"""
    recognition_result_signal = pyqtSignal(str, bool)  # 发送识别结果信号 (text, is_final)
    
    def __init__(self, model_path):
        """
        初始化识别器
        :param model_path: 模型路径
        """
        super().__init__()
        self.model_path = Path(model_path)
        self.model = None
        self.recognizer = None
        self.sample_rate = 16000
        self.audio_queue = queue.Queue()
        self.is_processing = False
        self.processing_thread = None
        
        # 加载模型
        self.load_model()
    
    def load_model(self):
        """加载 Vosk 模型"""
        try:
            if not self.model_path.exists():
                print(f"错误: 模型路径不存在: {self.model_path}")
                return False
            
            print(f"正在加载模型: {self.model_path}")
            self.model = Model(str(self.model_path))
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
            print("模型加载成功")
            return True
        except Exception as e:
            print(f"加载模型失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def start(self):
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
    
    def stop(self):
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
    
    def feed_audio(self, audio_data: bytes):
        """输入音频数据"""
        if self.is_processing and self.recognizer:
            self.audio_queue.put(audio_data)
    
    def _process_audio(self):
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
                    if text:
                        # 通过信号发送结果（线程安全）
                        self.recognition_result_signal.emit(text, True)
                else:
                    # 部分结果
                    result = json.loads(self.recognizer.PartialResult())
                    text = result.get('partial', '').strip()
                    if text:
                        # 通过信号发送结果（线程安全）
                        self.recognition_result_signal.emit(text, False)
                        
            except queue.Empty:
                continue
            except Exception as e:
                print(f"音频处理错误: {e}")
                import traceback
                traceback.print_exc()
                continue


class MainWindow(QMainWindow):
    """主窗口"""
    def __init__(self):
        super().__init__()
        self.audio_capture = None
        self.recognizer = None
        self.is_capturing = False
        self.init_ui()
        
        # 初始化音频捕获
        self.audio_capture = AudioCaptureThread()
        self.audio_capture.audio_data_signal.connect(self.on_audio_data)
        self.audio_capture.volume_updated_signal.connect(self.update_volume)
        self.audio_capture.device_name_updated_signal.connect(self.update_device_name)
        
        # 初始化识别器
        model_path = Path("models/vosk-model-ja-0.22")
        self.recognizer = VoskRecognizer(model_path)
        self.recognizer.recognition_result_signal.connect(self.update_recognition_text)
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("桌面音频捕获和语音识别测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        layout = QVBoxLayout(central_widget)
        
        # 设备信息标签
        self.device_label = QLabel("设备: 未选择")
        self.device_label.setStyleSheet("font-size: 14px; padding: 10px;")
        layout.addWidget(self.device_label)
        
        # 音量显示
        volume_label = QLabel("音量:")
        layout.addWidget(volume_label)
        
        self.volume_bar = QProgressBar()
        self.volume_bar.setMinimum(0)
        self.volume_bar.setMaximum(100)
        self.volume_bar.setValue(0)
        self.volume_bar.setFormat("%v%")
        self.volume_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                background-color: #1e1e1e;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.volume_bar)
        
        # 控制按钮
        self.start_button = QPushButton("开始捕获")
        self.start_button.clicked.connect(self.toggle_capture)
        layout.addWidget(self.start_button)
        
        # 识别结果文本框
        result_label = QLabel("识别结果:")
        layout.addWidget(result_label)
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("识别结果将显示在这里...")
        layout.addWidget(self.result_text)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
    def toggle_capture(self):
        """切换捕获状态"""
        if not self.is_capturing:
            # 开始捕获
            if self.audio_capture:
                self.audio_capture.start()
                self.recognizer.start()
                self.is_capturing = True
                self.start_button.setText("停止捕获")
                self.status_bar.showMessage("正在捕获音频...")
        else:
            # 停止捕获
            if self.audio_capture:
                self.audio_capture.stop_capture()
            if self.recognizer:
                self.recognizer.stop()
            self.is_capturing = False
            self.start_button.setText("开始捕获")
            self.update_volume(0.0)  # 停止时音量归零
            self.status_bar.showMessage("已停止捕获")
    
    def on_audio_data(self, audio_bytes: bytes):
        """接收音频数据（在主线程中调用）"""
        if self.recognizer and self.is_capturing:
            self.recognizer.feed_audio(audio_bytes)
    
    def update_device_name(self, device_name: str):
        """更新设备名称显示（通过信号调用，线程安全）"""
        self.device_label.setText(f"设备: {device_name}")
    
    def update_volume(self, volume: float):
        """更新音量显示（通过信号调用，线程安全）"""
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
    
    def update_recognition_text(self, text: str, is_final: bool):
        """更新识别文本（通过信号调用，线程安全）"""
        if not text or not text.strip():
            return
        
        if is_final:
            # 最终结果，追加新行
            current_text = self.result_text.toPlainText()
            if current_text:
                self.result_text.append(f"\n{text}")
            else:
                self.result_text.setText(text)
            # 滚动到底部
            self.result_text.verticalScrollBar().setValue(
                self.result_text.verticalScrollBar().maximum()
            )
            self.status_bar.showMessage(f"识别到: {text}", 3000)
        else:
            # 部分结果：更新最后一行
            current_text = self.result_text.toPlainText()
            lines = current_text.split('\n')
            if lines and not lines[-1].strip():
                lines.pop()
            if lines:
                lines[-1] = text
            else:
                lines = [text]
            self.result_text.setText('\n'.join(lines))
            # 滚动到底部
            self.result_text.verticalScrollBar().setValue(
                self.result_text.verticalScrollBar().maximum()
            )
    
    def closeEvent(self, event):
        """窗口关闭时清理资源"""
        if self.is_capturing:
            self.toggle_capture()
        if self.audio_capture:
            self.audio_capture.stop_capture()
        if self.recognizer:
            self.recognizer.stop()
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
