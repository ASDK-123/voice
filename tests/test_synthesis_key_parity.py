import unittest

from core.synthesis.cache_key import build_cache_identity


def _build_api_like_identity(*, text: str, voice_id: str, mode: str, prompt_text: str, instruct_text: str, variation_seed: int):
    return build_cache_identity(
        schema_version="cv_cache_v2",
        model_dir="pretrained_models/Fun-CosyVoice3-0.5B",
        fp16=False,
        load_trt=True,
        load_vllm=False,
        voice_id=voice_id,
        mode=mode,
        prompt_text=prompt_text,
        instruct_text=instruct_text,
        prompt_audio_hash="audio_sha1",
        selected_ref_asset_id="",
        variation_seed=variation_seed,
        text=text,
        speed=1.0,
        use_instruction=False,
        instruction="",
        is_v3=True,
        part_index=0,
    )


def _build_worker_like_identity(*, text: str, voice_id: str, mode: str, prompt_text: str, instruct_text: str, variation_seed: int):
    mode_l = (mode or "").lower()
    use_instruction = ("instruct" in mode_l) or ("指令" in (mode or ""))
    return build_cache_identity(
        schema_version="cv_cache_v2",
        model_dir="pretrained_models/Fun-CosyVoice3-0.5B",
        fp16=False,
        load_trt=True,
        load_vllm=False,
        voice_id=voice_id,
        mode=mode,
        prompt_text=prompt_text,
        instruct_text=instruct_text,
        prompt_audio_hash="audio_sha1",
        selected_ref_asset_id="",
        variation_seed=variation_seed,
        text=text,
        speed=1.0,
        use_instruction=use_instruction,
        instruction=(instruct_text if use_instruction else ""),
        is_v3=True,
        part_index=0,
    )


class TestSynthesisKeyParity(unittest.TestCase):
    def test_api_worker_key_parity_ref_mode(self):
        api_key = _build_api_like_identity(
            text="hello world",
            voice_id="Alice#default",
            mode="参考音色",
            prompt_text="hello",
            instruct_text="",
            variation_seed=1,
        )["request_hash"]
        worker_key = _build_worker_like_identity(
            text="hello world",
            voice_id="Alice#default",
            mode="参考音色",
            prompt_text="hello",
            instruct_text="",
            variation_seed=1,
        )["request_hash"]
        self.assertEqual(api_key, worker_key)

    def test_api_worker_key_parity_instruction_mode(self):
        api_key = build_cache_identity(
            schema_version="cv_cache_v2",
            model_dir="pretrained_models/Fun-CosyVoice3-0.5B",
            fp16=False,
            load_trt=True,
            load_vllm=False,
            voice_id="Alice#default",
            mode="指令控制",
            prompt_text="",
            instruct_text="保持平稳",
            prompt_audio_hash="audio_sha1",
            selected_ref_asset_id="",
            variation_seed=2,
            text="你好",
            speed=1.0,
            use_instruction=True,
            instruction="保持平稳",
            is_v3=True,
            part_index=0,
        )["request_hash"]
        worker_key = _build_worker_like_identity(
            text="你好",
            voice_id="Alice#default",
            mode="指令控制",
            prompt_text="",
            instruct_text="保持平稳",
            variation_seed=2,
        )["request_hash"]
        self.assertEqual(api_key, worker_key)


if __name__ == "__main__":
    unittest.main()
