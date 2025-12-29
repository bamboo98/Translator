"""
测试 Windows 11 实时字幕（LiveCaptions）的字幕获取
使用 Windows UI Automation API 来读取实时字幕窗口中的文本内容
"""
import time
import sys
from typing import Optional

try:
    import uiautomation as auto
except ImportError:
    print("错误: 未安装 uiautomation 库")
    print("请运行: pip install uiautomation")
    sys.exit(1)


class LiveCaptionsReader:
    """实时字幕读取器"""
    
    def __init__(self):
        self.window: Optional[auto.WindowControl] = None
        self.last_text = ""
        self.text_element: Optional[auto.Control] = None
        
    def find_window(self) -> bool:
        """
        查找实时字幕窗口
        
        Returns:
            bool: 是否找到窗口
        """
        # 方法1: 通过窗口标题查找
        try:
            self.window = auto.WindowControl(searchDepth=1, ClassName="LiveCaptionsDesktopWindow")
            if self.window.Exists(0, 0):
                return True
        except Exception as e:
            print(f"查找失败: {e}")
        
        print("✗ 未找到实时字幕窗口")
        return False
    
    def find_text_element(self) -> bool:
        """
        查找显示字幕文本的UI元素
        
        Returns:
            bool: 是否找到文本元素
        """
        if not self.window:
            return False
        
        try:
            # 通过 AutomationId 查找字幕控件
            print("\n通过 AutomationId 查找字幕控件...")
            element = self._find_caption_by_automation_id()
            
            if element and element.Exists(0, 0):
                # 验证找到的控件确实是字幕控件
                self.text_element = element
                print(f"✓ 找到字幕控件!")
                    
                # 尝试获取当前文本（可能为空）
                text = self._get_text_from_element(element)
                if text and text.strip():
                    print(f"\n当前文本预览: {text[:80]}...")
                else:
                    print(f"\n当前文本: (暂无字幕)")
                return True
            else:
                print("✗ 未找到字幕控件")
                return False
            
        except Exception as e:
            print(f"查找文本元素时出错: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _find_caption_by_automation_id(self) -> Optional[auto.Control]:
        """
        通过 AutomationId 直接查找字幕控件（最可靠的方法）
        使用固定特征: AutomationId = "CaptionsScrollViewer"
        """
        try:
            # 方法1: 在整个窗口中查找 AutomationId = "CaptionsScrollViewer" 的控件
            caption_control = self.window.Control(AutomationId="CaptionsScrollViewer")
            if caption_control.Exists(0, 0):
                print("  ✓ 通过 AutomationId 直接找到字幕控件")
                return caption_control
            
            print("  未找到 AutomationId = 'CaptionsScrollViewer' 的控件")
            return None
            
        except Exception as e:
            print(f"  通过 AutomationId 查找失败: {e}")
            return None
    
    def _get_text_from_element(self, element) -> str:
        """
        从元素获取文本，尝试多种方法
        
        Args:
            element: UI元素
            
        Returns:
            str: 文本内容
        """
        if not element:
            return ""
        
        #  使用 Name 属性
        try:
            return element.Name or ""
        except:
            pass
        
        return ""
    
    def get_current_text(self) -> str:
        """
        获取当前字幕文本
        
        Returns:
            str: 当前字幕文本，如果获取失败返回空字符串
        """
        if not self.text_element:
            return ""
        
        try:
            # 验证元素是否仍然存在
            if not self.text_element.Exists(0, 0):
                # 元素已失效，尝试重新查找
                print("警告: 文本元素已失效，尝试重新查找...")
                if self.find_text_element():
                    return self._get_text_from_element(self.text_element)
                return ""
            
            # 使用统一的文本获取方法
            return self._get_text_from_element(self.text_element)
            
        except Exception as e:
            # 静默处理错误，避免频繁打印（仅在调试时打印）
            # print(f"获取文本时出错: {e}")
            return ""
    
    def monitor(self, interval: float = 0.1, show_partial_updates: bool = True):
        """
        持续监控字幕变化
        
        Args:
            interval: 检查间隔（秒）
            show_partial_updates: 是否显示部分更新（实时字幕可能会逐步更新文本）
        """
        print("\n开始监控字幕变化...")
        print("按 Ctrl+C 停止监控\n")
        
        consecutive_errors = 0
        max_errors = 10
        
        try:
            while True:
                try:
                    current_text = self.get_current_text()
                    consecutive_errors = 0  # 重置错误计数
                    
                    # 检测文本变化
                    if current_text != self.last_text:
                        if current_text:
                            #输出最后一行
                            print(current_text.split('\n')[-1])
                        elif self.last_text:
                            # 文本被清空
                            print(f"[{time.strftime('%H:%M:%S')}] (字幕已清空)")
                        
                        self.last_text = current_text
                    elif show_partial_updates and current_text:
                        # 即使文本相同，也可能有部分更新（实时字幕会逐步追加）
                        # 这里可以添加更细粒度的检测，但为了性能，暂时只检测完全变化
                        pass
                    
                except Exception as e:
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        print(f"\n错误: 连续 {max_errors} 次获取文本失败，停止监控")
                        break
                    # 静默处理，避免频繁打印错误
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n监控已停止")


def main():
    """主函数"""
    print("=" * 60)
    print("Windows 11 实时字幕读取测试")
    print("=" * 60)
    print("\n提示: 请确保已开启 Windows 11 实时字幕功能")
    print("      (Win+Ctrl+L 或 设置 > 辅助功能 > 实时字幕)\n")
    
    reader = LiveCaptionsReader()
    
    # 查找窗口
    if not reader.find_window():
        return
    
    # 查找文本元素
    if not reader.find_text_element():
        print("\n提示: 如果窗口结构分析显示了文本内容，")
        print("      可以尝试手动指定控件类型或属性来获取文本")
        return
    
    # 开始监控
    reader.monitor(interval=0.1)


if __name__ == "__main__":
    main()
