# CosyVoice API 客户端
# 封装所有对 Docker API 的 HTTP 调用

import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class APIConfig:
    """API 配置"""
    host: str = "localhost"
    port: int = 9880
    
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class CosyVoiceAPIClient:
    """CosyVoice API 客户端"""
    
    def __init__(self, config: Optional[APIConfig] = None):
        self.config = config or APIConfig()
        self.timeout = 30.0
    
    def health_check(self) -> Dict[str, Any]:
        """检查 API 是否可用"""
        try:
            # Prefer v2 health; fall back to legacy endpoints.
            for path in ("/api/v2/health", "/api/health", "/health"):
                try:
                    response = httpx.get(f"{self.config.base_url}{path}", timeout=5.0)
                    response.raise_for_status()
                    return {"status": "ok", "data": response.json(), "path": path}
                except Exception:
                    continue
            return {"status": "error", "message": "health endpoints unavailable"}
        except httpx.ConnectError:
            return {"status": "error", "message": "无法连接到 API 服务器"}
        except httpx.TimeoutException:
            return {"status": "error", "message": "连接超时"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def list_speakers(self) -> List[str]:
        """获取可用角色列表"""
        # Server-side endpoints observed in this repo:
        # - GET /speakers (Tavern-compatible)
        # - GET /api/characters (legacy convenience)
        candidates = ("/api/v2/voices", "/speakers", "/api/characters")
        for path in candidates:
            try:
                response = httpx.get(f"{self.config.base_url}{path}", timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

                # v2 returns {"items":[{...}], "count": n}
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    names = []
                    for it in data.get("items") or []:
                        if isinstance(it, dict) and it.get("name"):
                            names.append(str(it["name"]))
                    if names:
                        return names

                # Most endpoints return a list of {"name": "...", "voice_id": "..."}.
                if isinstance(data, list):
                    names = []
                    for it in data:
                        if isinstance(it, dict) and it.get("name"):
                            names.append(str(it["name"]))
                    if names:
                        return names
                    continue

                # Be defensive if server returns {"speakers": [...]}.
                if isinstance(data, dict):
                    speakers = data.get("speakers", [])
                    if isinstance(speakers, list):
                        return [str(x) for x in speakers]
            except Exception:
                continue
        return []
    
    def generate_audio(self, text: str, speaker: str, speed: float = 1.0) -> Optional[bytes]:
        """生成音频（返回 WAV 字节流）"""
        try:
            # Prefer v2 synthesize; fall back to legacy root endpoint.
            try:
                response = httpx.post(
                    f"{self.config.base_url}/api/v2/synthesize",
                    json={"text": text, "voice_id": speaker, "speed": speed, "response_format": "audio"},
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.content
            except Exception:
                response = httpx.post(
                    f"{self.config.base_url}/",
                    json={"text": text, "speaker": speaker, "speed": speed},
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.content
        except Exception as e:
            print(f"生成音频失败: {e}")
            return None
    
    def generate_audio_stream(self, text: str, speaker: str, speed: float = 1.0):
        """生成音频（流式返回）"""
        try:
            # Prefer v2 synthesize; fall back to legacy root endpoint.
            try:
                with httpx.stream(
                    "POST",
                    f"{self.config.base_url}/api/v2/synthesize",
                    json={"text": text, "voice_id": speaker, "speed": speed, "response_format": "audio"},
                    timeout=self.timeout
                ) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        yield chunk
                return
            except Exception:
                pass

            with httpx.stream(
                "POST",
                f"{self.config.base_url}/",
                json={"text": text, "speaker": speaker, "speed": speed},
                timeout=self.timeout
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    yield chunk
        except Exception as e:
            print(f"流式生成失败: {e}")
    
    def generate_audio_direct(self, text: str, prompt_text: str, 
                               prompt_audio_path: str, speed: float = 1.0) -> Optional[bytes]:
        """
        直接生成音频（使用参考音频，无需角色配置）
        
        Args:
            text: 要合成的文本
            prompt_text: 参考音频对应的文本
            prompt_audio_path: 参考音频文件路径
            speed: 语速倍率
        
        Returns:
            WAV 音频字节流，失败返回 None
        """
        try:
            import base64
            
            # 读取音频文件并转为 base64
            with open(prompt_audio_path, 'rb') as f:
                audio_bytes = f.read()
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            response = httpx.post(
                f"{self.config.base_url}/api/tts_direct",
                json={
                    "text": text,
                    "prompt_text": prompt_text,
                    "prompt_audio_base64": audio_base64,
                    "speed": speed
                },
                timeout=60.0  # 直接 TTS 可能需要更长时间
            )
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"直接生成音频失败: {e}")
            return None
