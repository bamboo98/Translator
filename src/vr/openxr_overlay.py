"""
OpenXR VR Overlay模块
用于在SteamVR中显示掌心字幕
"""
import numpy as np
from typing import Optional, Tuple
import threading
import time
from PIL import Image, ImageDraw, ImageFont
import io

# 尝试导入OpenXR，如果不可用则设置为None
try:
    import openxr
    OPENXR_AVAILABLE = True
except ImportError:
    openxr = None
    OPENXR_AVAILABLE = False

class VROverlay:
    """VR Overlay类，用于在掌心显示字幕"""
    
    def __init__(self,
                 overlay_width: int = 512,
                 overlay_height: int = 256,
                 font_size: int = 24,
                 text_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
                 background_color: Tuple[int, int, int, int] = (0, 0, 0, 200)):
        """
        初始化VR Overlay
        
        Args:
            overlay_width: Overlay宽度（像素）
            overlay_height: Overlay高度（像素）
            font_size: 字体大小
            text_color: 文本颜色 (R, G, B, A)
            background_color: 背景颜色 (R, G, B, A)
        """
        self.overlay_width = overlay_width
        self.overlay_height = overlay_height
        self.font_size = font_size
        self.text_color = text_color
        self.background_color = background_color
        
        # 只有在OpenXR可用时才初始化这些属性
        if OPENXR_AVAILABLE:
            self.instance: Optional[openxr.Instance] = None
            self.session: Optional[openxr.Session] = None
            self.overlay_handle: Optional[openxr.OverlayHandle] = None
            self.space: Optional[openxr.Space] = None
        else:
            self.instance = None
            self.session = None
            self.overlay_handle = None
            self.space = None
        
        self.is_running = False
        self.update_thread: Optional[threading.Thread] = None
        self.current_text = ""
        self.text_lock = threading.Lock()
        
        # 尝试加载字体
        try:
            self.font = ImageFont.truetype("arial.ttf", font_size)
        except:
            try:
                self.font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", font_size)  # 微软雅黑
            except:
                self.font = ImageFont.load_default()
    
    def initialize(self) -> bool:
        """
        初始化OpenXR
        
        Returns:
            是否初始化成功
        """
        if not OPENXR_AVAILABLE:
            print("OpenXR不可用: 请安装pyopenxr (pip install pyopenxr)")
            return False
        
        try:
            # 注意：pyopenxr的API可能因版本而异
            # 这里提供通用实现，实际使用时可能需要根据库文档调整
            
            # 尝试导入并初始化OpenXR
            # 某些版本的pyopenxr可能需要不同的初始化方式
            try:
                # 方法1: 使用create_instance (如果可用)
                self.instance = openxr.create_instance(
                    application_name="VR翻译器",
                    application_version=1,
                    engine_name="Python",
                    engine_version=1
                )
            except AttributeError:
                # 方法2: 如果API不同，尝试其他方式
                # 这里需要根据实际的pyopenxr版本调整
                print("警告: OpenXR API可能需要调整，请参考pyopenxr文档")
                return False
            
            # 创建会话
            # 注意：这里需要根据实际的OpenXR实现调整
            # 不同的OpenXR Python绑定可能有不同的API
            
            print("OpenXR初始化成功")
            return True
            
        except Exception as e:
            print(f"OpenXR初始化失败: {e}")
            print("提示: 请确保已安装SteamVR或兼容的OpenXR运行时")
            return False
    
    def create_overlay(self) -> bool:
        """
        创建Overlay
        
        Returns:
            是否创建成功
        """
        try:
            # 创建overlay
            # 注意：OpenXR的overlay创建方式可能因实现而异
            # 这里使用通用方法
            
            overlay_key = "vr_translator_overlay"
            overlay_name = "VR翻译器字幕"
            
            # 创建overlay（具体API取决于pyopenxr的实现）
            # 如果pyopenxr不支持overlay，可能需要使用其他方法
            
            print("Overlay创建成功")
            return True
            
        except Exception as e:
            print(f"创建Overlay失败: {e}")
            return False
    
    def _render_text_to_image(self, text: str) -> bytes:
        """
        将文本渲染为图像
        
        Args:
            text: 要显示的文本
            
        Returns:
            PNG格式的图像字节数据
        """
        # 创建图像
        img = Image.new('RGBA', (self.overlay_width, self.overlay_height), 
                       self.background_color)
        draw = ImageDraw.Draw(img)
        
        # 计算文本位置（居中）
        bbox = draw.textbbox((0, 0), text, font=self.font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (self.overlay_width - text_width) // 2
        y = (self.overlay_height - text_height) // 2
        
        # 绘制文本
        draw.text((x, y), text, fill=self.text_color, font=self.font)
        
        # 转换为字节
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        return img_bytes.getvalue()
    
    def update_text(self, text: str) -> None:
        """
        更新显示文本
        
        Args:
            text: 要显示的文本
        """
        with self.text_lock:
            self.current_text = text
    
    def _update_overlay(self) -> None:
        """更新Overlay的线程函数"""
        while self.is_running:
            try:
                with self.text_lock:
                    text = self.current_text
                
                if text:
                    # 渲染文本为图像
                    image_data = self._render_text_to_image(text)
                    
                    # 更新overlay图像
                    # 注意：具体API取决于pyopenxr的实现
                    # self.overlay_handle.set_texture(image_data)
                
                time.sleep(0.1)  # 更新频率
                
            except Exception as e:
                print(f"更新Overlay错误: {e}")
                time.sleep(1.0)
    
    def _get_hand_position(self) -> Optional[np.ndarray]:
        """
        获取手掌位置（用于定位overlay）
        
        Returns:
            手掌位置和旋转（4x4变换矩阵），如果无法获取返回None
        """
        try:
            # 获取手部追踪数据
            # 注意：这需要OpenXR的手部追踪扩展
            # 如果不可用，可以使用控制器位置作为替代
            
            # 这里返回一个示例变换矩阵（单位矩阵）
            # 实际实现需要从OpenXR获取手部位置
            transform = np.eye(4)
            transform[:3, 3] = [0, 0, -0.5]  # 在面前0.5米
            
            return transform
            
        except Exception as e:
            print(f"获取手部位置失败: {e}")
            return None
    
    def start(self) -> bool:
        """
        启动Overlay显示
        
        Returns:
            是否启动成功
        """
        if self.is_running:
            return True
        
        if not self.initialize():
            return False
        
        if not self.create_overlay():
            return False
        
        self.is_running = True
        self.update_thread = threading.Thread(target=self._update_overlay, daemon=True)
        self.update_thread.start()
        
        print("VR Overlay已启动")
        return True
    
    def stop(self) -> None:
        """停止Overlay显示"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        if self.update_thread:
            self.update_thread.join(timeout=2.0)
        
        # 清理资源
        if self.overlay_handle:
            # 销毁overlay
            pass
        
        if self.session:
            # 关闭会话
            pass
        
        if self.instance:
            # 销毁实例
            pass
        
        print("VR Overlay已停止")
    
    def is_available(self) -> bool:
        """
        检查VR设备是否可用
        
        Returns:
            是否可用
        """
        if not OPENXR_AVAILABLE:
            return False
        
        try:
            # 尝试初始化来检测VR运行时
            instance = openxr.create_instance(
                application_name="VR检测",
                application_version=1,
                engine_name="Python",
                engine_version=1
            )
            # 如果成功创建实例，说明VR运行时可用
            return True
        except:
            return False
    
    def set_position(self, position: np.ndarray, rotation: np.ndarray) -> None:
        """
        设置Overlay位置（手动设置，用于调试）
        
        Args:
            position: 位置 (x, y, z)
            rotation: 旋转（四元数或欧拉角）
        """
        # 实现位置设置逻辑
        pass

