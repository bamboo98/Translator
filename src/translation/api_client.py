"""
翻译API客户端模块
支持硅基流动等在线翻译API和腾讯云机器翻译
"""
import httpx
import asyncio
from typing import Optional, Dict, Any, Callable, List, Tuple
import json
from enum import Enum

class TranslationProvider(Enum):
    """翻译服务提供商"""
    SILICONFLOW = "siliconflow"
    OPENAI = "openai"
    CUSTOM = "custom"

class TranslationClient:
    """翻译API客户端"""
    
    def __init__(self,
                 provider: str = "siliconflow",
                 api_key: str = "",
                 api_url: str = "",
                 model: str = "deepseek-chat",
                 timeout: int = 30,
                 trans_config: Optional[Dict[str, Any]] = None):
        """
        初始化翻译客户端
        
        Args:
            provider: 服务提供商
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            timeout: 请求超时时间（秒）
            trans_config: 翻译配置字典（用于获取提示词模板和API参数）
        """
        self.provider = TranslationProvider(provider)
        self.api_key = api_key
        self.api_url = api_url or self._get_default_url()
        self.model = model
        self.timeout = timeout
        self._trans_config = trans_config  # 保存配置以便_build_prompt使用
        
        # 从配置中读取 max_tokens 和 temperature
        if trans_config:
            self.max_tokens = trans_config.get("max_tokens", 8000)
            self.temperature = trans_config.get("temperature", 0.3)
        else:
            self.max_tokens = 8000
            self.temperature = 0.3
        
        self.client: Optional[httpx.AsyncClient] = None
        self._init_client()
    
    def _get_default_url(self) -> str:
        """获取默认API地址"""
        if self.provider == TranslationProvider.SILICONFLOW:
            return "https://api.siliconflow.cn/v1/chat/completions"
        elif self.provider == TranslationProvider.OPENAI:
            return "https://api.openai.com/v1/chat/completions"
        else:
            return ""
    
    def _init_client(self) -> None:
        """初始化HTTP客户端"""
        # 如果已有客户端，先关闭它
        if self.client:
            try:
                # 尝试关闭旧客户端（在同步上下文中）
                # 注意：这里不能使用 await，所以只能标记为需要关闭
                # 实际关闭会在下次异步调用时处理
                pass
            except:
                pass
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.api_key:
            if self.provider == TranslationProvider.SILICONFLOW:
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif self.provider == TranslationProvider.OPENAI:
                headers["Authorization"] = f"Bearer {self.api_key}"
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        
        # 创建新的客户端，它会自动绑定到当前线程的事件循环（如果有）
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout
        )
    
    def _build_prompt(self, text: str, context_prompt: str = "", last_text: str = "") -> str:
        """
        构建翻译提示词
        
        Args:
            text: 待翻译文本
            context_prompt: 上下文提示词（来自WeightedContextManager）
            last_text: 上一句话的原文
            
        Returns:
            完整的提示词
        """
        # 从配置获取提示词模板
        trans_config = getattr(self, '_trans_config', None)
        
        # 优先使用prompt_template
        prompt_template = ""
        if trans_config:
            prompt_template = trans_config.get("prompt_template", "")
        
        # 如果配置中也没有，使用默认模板
        if not prompt_template:
            prompt_template = """你是一个为VRChat提供实时翻译的专业同声传译助手
- 翻译成口语化的中文,保留语气词
- 原文为语音识别,可能存在断句问题和同/近音词错误,结合上下文推测完整且正确的语句
- 在翻译结果开头添加0~99的整数和分隔符|来表示该句话的重要性,越大会在前文中保留越久,供后文翻译参考
- 只输出权重和翻译结果,不需要任何解释

待翻译内容:
{text}

上一句:
{last}

前文(权重降序):
{context}"""
        
        # 如果无上下文，将{context}替换为"无"
        if not context_prompt:
            context_prompt = "无"
        
        # 如果没有上一句，将{last}替换为空
        if not last_text:
            last_text = "无"
        
        # 替换占位符
        prompt = prompt_template.replace("{context}", context_prompt).replace("{text}", text).replace("{last}", last_text)
        
        return prompt
    
    def _get_language_name(self, lang_code: str) -> str:
        """获取语言名称"""
        lang_map = {
            "zh": "中文",
            "en": "英文",
            "ja": "日文",
            "ko": "韩文",
            "fr": "法文",
            "de": "德文",
            "es": "西班牙文",
            "ru": "俄文"
        }
        return lang_map.get(lang_code, lang_code)
    
    def _build_request_data(self, text: str, context_prompt: str = "", last_text: str = "") -> Dict[str, Any]:
        """
        构建API请求数据
        
        Args:
            text: 待翻译文本
            context_prompt: 上下文提示词
            last_text: 上一句话的原文
            
        Returns:
            请求数据字典
        """
        prompt = self._build_prompt(text, context_prompt, last_text)
        
        if self.provider == TranslationProvider.SILICONFLOW:
            return {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "enable_thinking":False
            }
        elif self.provider == TranslationProvider.OPENAI:
            return {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "enable_thinking":False
            }
        else:
            # 通用格式
            return {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "enable_thinking":False
            }
    
    def _ensure_client_for_current_loop(self) -> None:
        """确保客户端绑定到当前线程的事件循环"""
        try:
            current_loop = asyncio.get_running_loop()
            # 如果客户端不存在或绑定到不同的事件循环，重新创建
            if not self.client:
                self._init_client()
            else:
                # 检查客户端是否绑定到当前事件循环
                # httpx.AsyncClient 内部使用的事件循环可以通过检查其状态来判断
                # 如果客户端已关闭或绑定到不同循环，重新创建
                try:
                    # 尝试获取客户端的事件循环（通过检查其内部状态）
                    # 如果无法确定，为了安全起见，重新创建客户端
                    if hasattr(self.client, '_transport') and self.client._transport is None:
                        # 传输层已关闭，需要重新创建
                        self._init_client()
                except:
                    # 如果检查失败，重新创建客户端以确保安全
                    self._init_client()
        except RuntimeError:
            # 没有运行中的事件循环，但客户端可能仍然有效
            if not self.client:
                self._init_client()
    
    async def translate_async(self, text: str, context_prompt: str = "", last_text: str = "") -> Optional[str]:
        """
        异步翻译文本
        
        Args:
            text: 待翻译文本
            context_prompt: 上下文提示词（可选）
            last_text: 上一句话的原文（可选）
            
        Returns:
            翻译结果，如果失败返回None
        """
        if not text or not text.strip():
            return None
        
        if not self.api_key:
            print("错误: API密钥未设置")
            return None
        
        # 确保客户端绑定到当前事件循环
        self._ensure_client_for_current_loop()
        
        import json
        import time
        request_data = None
        try:
            request_data = self._build_request_data(text, context_prompt, last_text)
            
            try:
                post_start_time = time.time()
                response = await self.client.post(
                    self.api_url,
                    json=request_data
                )
                post_time = time.time() - post_start_time
                # print(f"[完整翻译] client.post实际耗时: {post_time:.3f}秒")
            except RuntimeError as e:
                # 如果遇到事件循环绑定错误，重新创建客户端并重试
                if "bound to a different event loop" in str(e):
                    self._init_client()
                    post_start_time = time.time()
                    response = await self.client.post(
                        self.api_url,
                        json=request_data
                    )
                    post_time = time.time() - post_start_time
                    # print(f"[完整翻译] client.post实际耗时(重试): {post_time:.3f}秒")
                else:
                    raise
            
            response.raise_for_status()
            result = response.json()
            
            # 解析响应
            if self.provider in [TranslationProvider.SILICONFLOW, TranslationProvider.OPENAI]:
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0].get("message", {}).get("content", "")
                    if content:
                        return content.strip()
            else:
                # 尝试通用解析
                if "choices" in result:
                    content = result["choices"][0].get("message", {}).get("content", "")
                    if content:
                        return content.strip()
                elif "text" in result:
                    return result["text"].strip()
                elif "translation" in result:
                    return result["translation"].strip()
            
            print(f"无法解析API响应: {result}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
            
        except httpx.HTTPStatusError as e:
            print(f"翻译API HTTP错误: {e.response.status_code} - {e.response.text}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
        except httpx.RequestError as e:
            print(f"翻译API请求错误: {e}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
        except Exception as e:
            print(f"翻译API未知错误: {e}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
    
    def translate(self, text: str, context_prompt: str = "", last_text: str = "") -> Optional[str]:
        """
        同步翻译文本（内部使用异步）
        
        Args:
            text: 待翻译文本
            context_prompt: 上下文提示词（可选）
            last_text: 上一句话的原文（可选）
            
        Returns:
            翻译结果
        """
        # 获取或创建当前线程的事件循环
        try:
            # 尝试获取当前线程的事件循环
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                # 如果事件循环已关闭，创建新的
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # 重新创建客户端以绑定到新的事件循环
                self._init_client()
        except RuntimeError:
            # 如果没有事件循环，创建新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # 重新创建客户端以绑定到新的事件循环
            self._init_client()
        
        # 检查是否在运行中的事件循环中
        try:
            running_loop = asyncio.get_running_loop()
            # 如果在运行中的事件循环中，不能使用 run_until_complete
            # 这种情况下应该使用异步方法
            raise RuntimeError("Cannot use translate() in async context, use translate_async() instead")
        except RuntimeError:
            # 没有运行中的事件循环，可以使用 run_until_complete
            try:
                return loop.run_until_complete(self.translate_async(text, context_prompt, last_text))
            except Exception as e:
                # 如果事件循环已关闭或客户端绑定错误，创建新的并重试
                error_str = str(e)
                if "Event loop is closed" in error_str or "bound to a different event loop" in error_str or loop.is_closed():
                    # 重新创建客户端以绑定到新的事件循环
                    self._init_client()
                    # 如果事件循环已关闭，创建新的
                    if loop.is_closed():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    return loop.run_until_complete(self.translate_async(text, context_prompt, last_text))
                raise
    
    def translate_with_prompt(self, text: str, prompt: str) -> Optional[str]:
        """
        使用自定义提示词同步翻译文本（内部使用异步）
        
        Args:
            text: 待翻译文本
            prompt: 自定义提示词
            
        Returns:
            翻译结果
        """
        # 获取或创建当前线程的事件循环
        try:
            # 尝试获取当前线程的事件循环
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                # 如果事件循环已关闭，创建新的
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # 重新创建客户端以绑定到新的事件循环
                self._init_client()
        except RuntimeError:
            # 如果没有事件循环，创建新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # 重新创建客户端以绑定到新的事件循环
            self._init_client()
        
        # 检查是否在运行中的事件循环中
        try:
            running_loop = asyncio.get_running_loop()
            # 如果在运行中的事件循环中，不能使用 run_until_complete
            # 这种情况下应该使用异步方法
            raise RuntimeError("Cannot use translate_with_prompt() in async context, use translate_async_with_prompt() instead")
        except RuntimeError:
            # 没有运行中的事件循环，可以使用 run_until_complete
            try:
                return loop.run_until_complete(self.translate_async_with_prompt(text, prompt))
            except Exception as e:
                # 如果事件循环已关闭或客户端绑定错误，创建新的并重试
                error_str = str(e)
                if "Event loop is closed" in error_str or "bound to a different event loop" in error_str or loop.is_closed():
                    # 重新创建客户端以绑定到新的事件循环
                    self._init_client()
                    # 如果事件循环已关闭，创建新的
                    if loop.is_closed():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    return loop.run_until_complete(self.translate_async_with_prompt(text, prompt))
                raise
    
    async def translate_async_with_prompt(self, text: str, prompt: str) -> Optional[str]:
        """
        使用自定义提示词异步翻译文本
        
        Args:
            text: 待翻译文本
            prompt: 自定义提示词
            
        Returns:
            翻译结果，如果失败返回None
        """
        if not text or not text.strip():
            return None
        
        if not self.api_key:
            print("错误: API密钥未设置")
            return None
        
        # 确保客户端绑定到当前事件循环
        self._ensure_client_for_current_loop()
        
        import json
        import time
        request_data = None
        try:
            request_data = self._build_request_data_with_prompt(prompt)
            
            try:
                post_start_time = time.time()
                response = await self.client.post(
                    self.api_url,
                    json=request_data
                )
                post_time = time.time() - post_start_time
                # print(f"[即时翻译] client.post实际耗时: {post_time:.3f}秒")
            except RuntimeError as e:
                # 如果遇到事件循环绑定错误，重新创建客户端并重试
                if "bound to a different event loop" in str(e):
                    self._init_client()
                    post_start_time = time.time()
                    response = await self.client.post(
                        self.api_url,
                        json=request_data
                    )
                    post_time = time.time() - post_start_time
                    # print(f"[即时翻译] client.post实际耗时(重试): {post_time:.3f}秒")
                else:
                    raise
            
            response.raise_for_status()
            result = response.json()
            
            # 解析响应
            if self.provider in [TranslationProvider.SILICONFLOW, TranslationProvider.OPENAI]:
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0].get("message", {}).get("content", "")
                    return content.strip()
            else:
                # 尝试通用解析
                if "choices" in result:
                    content = result["choices"][0].get("message", {}).get("content", "")
                    return content.strip()
                elif "text" in result:
                    return result["text"].strip()
                elif "translation" in result:
                    return result["translation"].strip()
            
            print(f"无法解析API响应: {result}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
            
        except httpx.HTTPStatusError as e:
            print(f"翻译API HTTP错误: {e.response.status_code} - {e.response.text}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
        except httpx.RequestError as e:
            print(f"翻译API请求错误: {e}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
        except Exception as e:
            print(f"翻译API未知错误: {e}")
            if request_data:
                print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
            return None
    
    def _build_request_data_with_prompt(self, prompt: str) -> Dict[str, Any]:
        """
        使用自定义提示词构建API请求数据
        
        Args:
            prompt: 自定义提示词
            
        Returns:
            请求数据字典
        """
        if self.provider == TranslationProvider.SILICONFLOW:
            return {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "enable_thinking":False 
            }
        elif self.provider == TranslationProvider.OPENAI:
            return {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "enable_thinking":False 
            }
        else:
            # 通用格式
            return {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "enable_thinking":False 
            }
    
    async def translate_batch_async(self, texts: List[str]) -> List[Optional[str]]:
        """
        批量异步翻译
        
        Args:
            texts: 待翻译文本列表
            
        Returns:
            翻译结果列表
        """
        tasks = [self.translate_async(text) for text in texts]
        return await asyncio.gather(*tasks)
    
    def update_config(self,
                     api_key: Optional[str] = None,
                     api_url: Optional[str] = None,
                     model: Optional[str] = None,
                     trans_config: Optional[Dict[str, Any]] = None) -> None:
        """
        更新配置
        
        Args:
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            trans_config: 翻译配置字典（用于更新提示词模板和API参数）
        """
        if api_key is not None:
            self.api_key = api_key
        if api_url is not None:
            self.api_url = api_url
        if model is not None:
            self.model = model
        if trans_config is not None:
            self._trans_config = trans_config
            # 更新 max_tokens 和 temperature
            self.max_tokens = trans_config.get("max_tokens", 8000)
            self.temperature = trans_config.get("temperature", 0.3)
        
        # 重新初始化客户端
        if self.client:
            # 异步关闭客户端
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.client.aclose())
                else:
                    loop.run_until_complete(self.client.aclose())
            except RuntimeError:
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.client.aclose())
                    loop.close()
                except:
                    pass
        self._init_client()
    
    def close(self) -> None:
        """关闭客户端"""
        if self.client:
            # AsyncClient 需要使用 aclose() 方法，但需要在异步上下文中调用
            # 这里使用同步方式关闭
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果事件循环正在运行，创建任务
                    asyncio.create_task(self.client.aclose())
                else:
                    # 如果事件循环未运行，直接运行
                    loop.run_until_complete(self.client.aclose())
            except RuntimeError:
                # 如果没有事件循环，创建新的
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.client.aclose())
                    loop.close()
                except:
                    pass
            self.client = None
    
    async def translate_tencent_async(self, text: str, source_lang: str = "auto", target_lang: str = "zh", 
                                      secret_id: str = "", secret_key: str = "", region: str = "ap-beijing",
                                      project_id: int = 0) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """
        使用腾讯云机器翻译API进行翻译（异步）
        
        Args:
            text: 待翻译文本
            source_lang: 源语言代码（auto表示自动检测）
            target_lang: 目标语言代码（zh=中文, zh-TW=繁体中文, en=英文, ja=日文等）
            secret_id: 腾讯云SecretId
            secret_key: 腾讯云SecretKey
            region: 腾讯云区域
            project_id: 项目ID
            
        Returns:
            (翻译结果, 已消耗字符数, 错误信息) 的元组
            如果成功，返回 (翻译结果, 字符数, None)
            如果失败，返回 (None, None, 错误信息)
        """
        if not text or not text.strip():
            return None, None, "文本为空"
        
        if not secret_id or not secret_key:
            return None, None, "腾讯云API密钥未设置"
        
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.tmt.v20180321 import tmt_client, models
        except ImportError:
            return None, None, "腾讯云SDK未安装，请运行: pip install tencentcloud-sdk-python-tmt"
        
        try:
            # 创建凭证对象
            cred = credential.Credential(secret_id, secret_key)
            
            # 实例化http选项
            httpProfile = HttpProfile()
            httpProfile.endpoint = "tmt.tencentcloudapi.com"
            
            # 实例化client选项
            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile
            
            # 实例化要请求产品的client对象
            client = tmt_client.TmtClient(cred, region, clientProfile)
            
            # 实例化请求对象
            req = models.TextTranslateRequest()
            req.SourceText = text
            req.Source = source_lang
            req.Target = target_lang
            req.ProjectId = project_id
            
            # 调用接口（注意：腾讯云SDK是同步的，需要在异步环境中使用线程池）
            import concurrent.futures
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                resp = await loop.run_in_executor(executor, client.TextTranslate, req)
            
            # 解析响应
            if hasattr(resp, 'TargetText'):
                used_chars = getattr(resp, 'UsedAmount', 0) if hasattr(resp, 'UsedAmount') else len(text.encode('utf-8'))
                return resp.TargetText, used_chars, None
            else:
                return None, None, "API响应格式错误"
                
        except Exception as e:
            error_msg = self._parse_tencent_error(e)
            return None, None, error_msg
    
    def _parse_tencent_error(self, error: Exception) -> str:
        """
        解析腾讯云API错误，返回中文描述
        
        Args:
            error: 异常对象
            
        Returns:
            中文错误描述
        """
        error_str = str(error)
        
        # 公共错误码映射
        common_errors = {
            "AuthFailure": "签名验证失败，请检查SecretId和SecretKey是否正确",
            "AuthFailure.SecretIdNotFound": "SecretId不存在",
            "AuthFailure.SignatureExpire": "签名已过期",
            "AuthFailure.SignatureFailure": "签名错误",
            "InvalidParameter": "参数错误",
            "InvalidParameterValue": "参数值错误",
            "MissingParameter": "缺少必需参数",
            "RequestLimitExceeded": "请求频率超过限制",
            "ResourceInsufficient": "资源不足",
            "ResourceNotFound": "资源不存在",
            "ResourceUnavailable": "资源不可用",
            "UnauthorizedOperation": "未授权操作",
            "UnknownParameter": "未知参数",
            "UnsupportedOperation": "不支持的操作",
        }
        
        # 接口特定错误码
        api_errors = {
            "InvalidParameterValue.SourceTextEmpty": "待翻译文本为空",
            "InvalidParameterValue.SourceTextTooLong": "待翻译文本过长",
            "InvalidParameterValue.SourceLanguageNotSupported": "不支持的源语言",
            "InvalidParameterValue.TargetLanguageNotSupported": "不支持的目标语言",
            "InvalidParameterValue.SourceTargetSame": "源语言和目标语言相同",
            "LimitExceeded": "请求频率超过限制",
            "ResourceInsufficient": "资源不足",
        }
        
        # 尝试匹配错误码
        for error_code, description in {**common_errors, **api_errors}.items():
            if error_code in error_str:
                return f"{description} ({error_code})"
        
        # 如果没有匹配到，返回原始错误信息
        return f"腾讯云API错误: {error_str}"

