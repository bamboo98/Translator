"""
上下文管理器
支持AI决定的权重和时间衰减机制
"""
from typing import List, Tuple, Optional
import time
from dataclasses import dataclass

@dataclass
class ContextItem:
    """上下文项"""
    text: str  # 原文
    weight: float  # 原始权重（100-199）
    timestamp: float  # 保存时间戳
    
    def get_current_weight(self, memory_time: float, current_time: float) -> float:
        """
        计算当前权重（考虑时间衰减）
        
        Args:
            memory_time: 记忆时间（秒）
            current_time: 当前时间戳
            
        Returns:
            当前权重
        """
        elapsed = current_time - self.timestamp
        
        # 如果超出记忆时间，权重视为0
        if elapsed >= memory_time:
            return 0.0
        
        # 线性衰减：权重随时间的增加而减少
        # 衰减因子 = 1 - (已过时间 / 记忆时间)
        decay_factor = 1.0 - (elapsed / memory_time)
        return self.weight * decay_factor

class WeightedContextManager:
    """加权上下文管理器（支持时间衰减）"""
    
    def __init__(self, max_count: int = 10, memory_time: float = 300.0):
        """
        初始化上下文管理器
        
        Args:
            max_count: 最大记忆条数
            memory_time: 记忆时间（秒），默认300秒（5分钟）
        """
        self.max_count = max_count
        self.memory_time = memory_time
        self.contexts: List[ContextItem] = []
        self.last_text: Optional[str] = None  # 上一句话的原文
    
    def add_context(self, text: str, weight: float = 100.0) -> None:
        """
        添加上下文
        
        Args:
            text: 文本内容（原文）
            weight: 权重值（100-199，100为默认，100+AI权重）
        """
        if text and text.strip():
            # 更新上一句话
            if self.contexts:
                self.last_text = self.contexts[-1].text
            else:
                self.last_text = None
            
            # 添加上下文项
            item = ContextItem(
                text=text.strip(),
                weight=weight,
                timestamp=time.time()
            )
            self.contexts.append(item)
    
    def get_context(self) -> str:
        """
        获取上下文字符串（按当前权重排序，只返回文本）
        
        Returns:
            格式化的上下文字符串（只包含文本，不包含前缀）
        """
        if not self.contexts:
            return ""
        
        current_time = time.time()
        
        # 计算每个上下文的当前权重
        items_with_current_weight = []
        for item in self.contexts:
            current_weight = item.get_current_weight(self.memory_time, current_time)
            items_with_current_weight.append((item, current_weight))
        
        # 排序规则：
        # 1. 当前权重>0的，按当前权重倒序
        # 2. 当前权重<=0的，按保存时间降序
        def sort_key(item_weight_pair):
            item, current_weight = item_weight_pair
            if current_weight > 0:
                # 权重>0的，按权重倒序（权重大的在前）
                return (-current_weight, 0)  # 负数表示倒序
            else:
                # 权重<=0的，按时间戳倒序（新的在前）
                return (0, -item.timestamp)
        
        items_with_current_weight.sort(key=sort_key)
        
        # 移除超出最大条数的缓存
        if len(items_with_current_weight) > self.max_count:
            items_with_current_weight = items_with_current_weight[:self.max_count]
        
        # 只返回文本，不添加前缀
        context_lines = [item.text for item, _ in items_with_current_weight]
        
        return "\n".join(context_lines)
    
    def get_context_detail(self) -> str:
        """
        获取详细的上下文字符串（包含当前权重和剩余保存时间）
        
        Returns:
            格式化的详细上下文字符串，每行包含：文本、当前权重、剩余时间(秒)
        """
        if not self.contexts:
            return "（无上下文）"
        
        current_time = time.time()
        
        # 计算每个上下文的当前权重和剩余时间
        items_with_detail = []
        for item in self.contexts:
            elapsed = current_time - item.timestamp
            remaining_time = max(0.0, self.memory_time - elapsed)
            current_weight = item.get_current_weight(self.memory_time, current_time)
            items_with_detail.append((item, current_weight, remaining_time))
        
        # 排序规则：与get_context相同
        def sort_key(item_detail):
            item, current_weight, _ = item_detail
            if current_weight > 0:
                return (-current_weight, 0)
            else:
                return (0, -item.timestamp)
        
        items_with_detail.sort(key=sort_key)
        
        # 移除超出最大条数的缓存
        if len(items_with_detail) > self.max_count:
            items_with_detail = items_with_detail[:self.max_count]
        
        # 格式化输出
        detail_lines = []
        for item, current_weight, remaining_time in items_with_detail:
            # 格式化权重（保留1位小数）
            weight_str = f"{current_weight:.1f}"
            # 格式化剩余时间（保留1位小数）
            time_str = f"{remaining_time:.1f}"
            # 限制文本长度，避免tooltip过长
            text = item.text
            if len(text) > 50:
                text = text[:47] + "..."
            detail_lines.append(f"权重:{weight_str} | {time_str}秒 | {text}")
        
        return "\n".join(detail_lines)
    
    def get_last_text(self) -> str:
        """
        获取上一句话的原文
        
        Returns:
            上一句话的原文，如果没有则返回空字符串
        """
        return self.last_text if self.last_text else ""
    
    def clear(self) -> None:
        """清空所有上下文"""
        self.contexts.clear()
        self.last_text = None
    
    def update_config(self, max_count: Optional[int] = None, memory_time: Optional[float] = None) -> None:
        """
        更新配置
        
        Args:
            max_count: 最大记忆条数
            memory_time: 记忆时间（秒）
        """
        if max_count is not None:
            self.max_count = max_count
        if memory_time is not None:
            self.memory_time = memory_time
