"""
Windows 11 实时字幕（LiveCaptions）监听引擎
使用 Windows UI Automation API 来读取实时字幕窗口中的文本内容
"""
import time
import threading
from typing import Optional, Callable

try:
    import uiautomation as auto
except ImportError:
    print("警告: 未安装 uiautomation 库，实时字幕功能将不可用")
    auto = None


class LiveCaptionsEngine:
    """实时字幕监听引擎"""
    
    def __init__(self, callback: Optional[Callable] = None):
        """
        初始化实时字幕引擎
        
        Args:
            callback: 识别结果回调函数 (text, is_final, spk_embedding, speaker_id, feature_hash)
                     对于实时字幕，spk_embedding=None, speaker_id=1, feature_hash=""
        """
        self.callback = callback
        self.window: Optional[auto.WindowControl] = None
        self.text_element: Optional[auto.Control] = None
        self.is_processing = False
        self.processing_thread: Optional[threading.Thread] = None
        
        # 字幕内容管理
        self.last_full_text = ""  # 上次获取的完整文本
        self.last_lines = []  # 上次的行列表
        self.is_finish = True  # 当前话是否已结束
        self.last_change_time = 0  # 上次文本变化的时间
        self.last_output_final_text = ""  # 上次输出的完整句子（用于去重）
    
    def find_window(self) -> bool:
        """
        查找实时字幕窗口
        
        Returns:
            bool: 是否找到窗口
        """
        if auto is None:
            return False
        
        try:
            self.window = auto.WindowControl(searchDepth=1, ClassName="LiveCaptionsDesktopWindow")
            if self.window.Exists(0, 0):
                return True
        except Exception as e:
            pass
        
        return False
    
    def find_text_element(self) -> bool:
        """
        查找显示字幕文本的UI元素
        
        Returns:
            bool: 是否找到文本元素
        """
        if auto is None or not self.window:
            return False
        
        try:
            # 通过 AutomationId 查找字幕控件
            element = self.window.Control(AutomationId="CaptionsScrollViewer")
            if element and element.Exists(0, 0):
                self.text_element = element
                return True
        except Exception as e:
            pass
        
        return False
    
    def _get_text_from_element(self, element) -> str:
        """
        从元素获取文本
        
        Args:
            element: UI元素
            
        Returns:
            str: 文本内容
        """
        if not element or auto is None:
            return ""
        
        try:
            if not element.Exists(0, 0):
                return ""
            return element.Name or ""
        except:
            return ""
    
    def get_current_text(self) -> str:
        """
        获取当前字幕文本
        
        Returns:
            str: 当前字幕文本，如果获取失败返回空字符串
        """
        if auto is None:
            return ""
        
        # 如果窗口或元素不存在，尝试重新查找
        if not self.window or not self.window.Exists(0, 0):
            if not self.find_window():
                return ""
            if not self.find_text_element():
                return ""
        
        if not self.text_element:
            if not self.find_text_element():
                return ""
        
        try:
            # 验证元素是否仍然存在
            if not self.text_element.Exists(0, 0):
                # 元素已失效，尝试重新查找
                if not self.find_text_element():
                    return ""
            
            # 获取文本
            return self._get_text_from_element(self.text_element)
        except Exception as e:
            # 静默处理错误
            return ""
    
    def _process_captions(self) -> None:
        """字幕处理线程"""
        while self.is_processing:
            try:
                current_text = self.get_current_text()
                current_time = time.time()
                last_line_update = None
                
                # 处理空字符串
                if not current_text or not current_text.strip():
                    # 如果之前有内容，现在为空，视为清空
                    if self.last_full_text and self.last_full_text.strip():
                        self.last_full_text = ""
                        self.last_lines = []
                        self.last_change_time = current_time
                    time.sleep(0.1)
                    continue
                
                # 按换行符分割
                current_lines = [line.strip() for line in current_text.split('\n') if line.strip()]
                
                # 检测文本变化
                if current_text != self.last_full_text:
                    self.last_change_time = current_time
                    self.last_full_text = current_text
                    
                    # 处理行变化
                    if len(current_lines) >= 1:
                        # 有至少1行
                        last_line = current_lines[-1]  # 最后一行（当前输出）
                        
                        # 检查最后一行是否更新
                        last_line_changed = len(self.last_lines) == 0 or (len(current_lines) > 0 and current_lines[-1] != (self.last_lines[-1] if self.last_lines else ""))
                        
                        # 如果最后一行更新了，输出部分结果
                        if last_line_changed:
                            last_line_update = last_line
                            # 放到后面再更新,防止这里更新顺序错误导致输出BUG
                            # if self.callback:
                            #     self.callback(last_line, False, None, 1, "")
                        
                        # 如果有倒数第二行
                        if len(current_lines) >= 2:
                            second_last_line = current_lines[-2]  # 倒数第二行（上一句完整的话）
                            
                            # 检查倒数第二行是否变化（说明最后一行变成了倒数第二行，新的一行出现了）
                            second_last_changed = len(self.last_lines) < 2 or (len(self.last_lines) >= 2 and second_last_line != self.last_lines[-2])
                            
                            if second_last_changed:
                                # 倒数第二行变化了
                                if not self.is_finish:
                                    # 如果当前话未结束，视为倒数第二行结束（输出倒数第二行结束）
                                    if self.callback and second_last_line != self.last_output_final_text:
                                        # print('倒数第二行输出:', second_last_line)
                                        # self.callback(second_last_line, False, None, 1, "")
                                        self.callback(second_last_line, True, None, 1, "")
                                        self.last_output_final_text = second_last_line
                                else:
                                    # 如果当前话已结束，重置状态（不再重复输出结束事件）
                                    self.is_finish = False
                        
                        # 更新last_lines
                        self.last_lines = current_lines.copy()
                    else:
                        # 没有行，清空
                        self.last_lines = []
                else:
                    # 文本没有变化
                    # 检查是否连续无变化
                    if current_time - self.last_change_time >= 2.5:
                        # 连续2秒无变化，视为最后一行结束
                        if not self.is_finish and len(current_lines) >= 1:
                            last_line = current_lines[-1]
                            self.is_finish = True
                            if self.callback and last_line != self.last_output_final_text:
                                # print('强制输出最后一行:', last_line)
                                # self.callback(last_line, False, None, 1, "")
                                self.callback(last_line, True, None, 1, "")
                                self.last_output_final_text = last_line
                
                if last_line_update:
                    if self.callback:
                        self.callback(last_line_update, False, None, 1, "")
                    last_line_update = None
                time.sleep(0.1)
                
            except Exception as e:
                # 静默处理错误，继续运行
                time.sleep(0.1)
                continue
    
    def start(self) -> bool:
        """
        启动字幕监听
        
        Returns:
            bool: 是否启动成功
        """
        if self.is_processing:
            return True
        
        if auto is None:
            print("错误: uiautomation 库未安装，无法启动实时字幕监听")
            return False
        
        # 查找窗口和文本元素
        if not self.find_window():
            print("警告: 未找到实时字幕窗口，请确保已开启 Windows 11 实时字幕")
            return False
        
        if not self.find_text_element():
            print("警告: 未找到字幕文本元素，请确保实时字幕窗口已完全加载")
            return False
        
        # 重置状态
        self.last_full_text = ""
        self.last_lines = []
        self.is_finish = True
        self.last_change_time = time.time()
        self.last_output_final_text = ""
        
        # 启动处理线程
        self.is_processing = True
        self.processing_thread = threading.Thread(target=self._process_captions, daemon=True)
        self.processing_thread.start()
        
        print("实时字幕监听已启动")
        return True
    
    def stop(self) -> None:
        """停止字幕监听"""
        if not self.is_processing:
            return
        
        self.is_processing = False
        
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=1.0)
        
        # 清空引用
        self.window = None
        self.text_element = None
        
        print("实时字幕监听已停止")
