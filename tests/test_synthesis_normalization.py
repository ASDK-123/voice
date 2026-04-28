import unittest

from core.synthesis.cache_key import build_cache_identity
from core.synthesis.normalize import (
    apply_instruction_override,
    clean_text_for_inference,
    normalize_inference_mode,
    normalize_prompt_and_instruct,
    normalize_request_text,
)
from core.synthesis.resolve_voice import parse_voice_id
from core.synthesis.select_ref import select_ref_asset_id
from core.v2.asset_texts import resolve_prompt_text_voice_first


class TestSynthesisNormalization(unittest.TestCase):
    def test_normalize_request_text(self):
        self.assertEqual(normalize_request_text("  A\t\tB  "), "A B")
        self.assertEqual(normalize_request_text("a\n\n\n\nb"), "a\n\nb")
        self.assertEqual(clean_text_for_inference("  A\t\tB  "), "A B")

    def test_instruction_override(self):
        mode, instruct_text = apply_instruction_override(
            mode="参考音色",
            instruct_text="old",
            use_instruction=True,
            instruction="new_instruct",
        )
        self.assertTrue(mode)
        self.assertEqual(instruct_text, "new_instruct")

    def test_cv3_prompt_and_instruct_normalization(self):
        prompt_final, _ = normalize_prompt_and_instruct(
            mode="参考音色",
            prompt_text="hello",
            instruct_text="",
            is_v3=True,
        )
        self.assertIn("<|endofprompt|>", prompt_final)
        self.assertTrue(prompt_final.startswith("You are a helpful assistant."))

        _, instruct_final = normalize_prompt_and_instruct(
            mode="指令控制",
            prompt_text="",
            instruct_text="说话自然",
            is_v3=True,
        )
        self.assertIn("<|endofprompt|>", instruct_final)
        self.assertIn("You are a helpful assistant.", instruct_final)

    def test_parse_voice_id(self):
        self.assertEqual(parse_voice_id("Alice#happy"), ("Alice", "happy"))
        self.assertEqual(parse_voice_id("Alice"), ("Alice", "default"))
        self.assertEqual(parse_voice_id(""), ("", "default"))

    def test_mode_normalization(self):
        self.assertEqual(normalize_inference_mode("zero-shot"), "zero_shot")
        self.assertEqual(normalize_inference_mode("reference_timbre"), "reference_timbre")
        self.assertEqual(normalize_inference_mode("指令控制"), "instruction")
        self.assertEqual(normalize_inference_mode("精细控制"), "fine_grained")

    def test_ref_selection_is_deterministic(self):
        voice = {
            "character": "Alice",
            "emotion": "default",
            "selection_policy": "random_per_text",
            "ref_asset_ids": ["r1", "r2", "r3"],
        }
        a = select_ref_asset_id(voice=voice, text="hello world", variation_seed=7)
        b = select_ref_asset_id(voice=voice, text="hello world", variation_seed=7)
        self.assertEqual(a, b)

        c = select_ref_asset_id(
            voice=voice,
            text="hello world",
            variation_seed=7,
            selected_ref_asset_id="manual_ref",
        )
        self.assertEqual(c, "manual_ref")

    def test_cache_identity_stability(self):
        common = dict(
            schema_version="cv_cache_v2",
            model_dir="pretrained_models/Fun-CosyVoice3-0.5B",
            fp16=False,
            load_trt=True,
            load_vllm=False,
            voice_id="Alice#default",
            mode="参考音色",
            prompt_text="hello",
            instruct_text="",
            prompt_audio_hash="abc123",
            selected_ref_asset_id="ref_x",
            variation_seed=1,
            text="  hello   world  ",
            speed=1.0,
            use_instruction=False,
            instruction="",
            is_v3=True,
            part_index=0,
        )
        x = build_cache_identity(**common)
        y = build_cache_identity(**common)
        self.assertEqual(x["request_hash"], y["request_hash"])

        z = build_cache_identity(**{**common, "variation_seed": 2})
        self.assertNotEqual(x["request_hash"], z["request_hash"])

        k = build_cache_identity(**{**common, "selected_ref_asset_id": "ref_y"})
        self.assertNotEqual(x["request_hash"], k["request_hash"])

    def test_prompt_resolution_order_voice_first(self):
        text, src = resolve_prompt_text_voice_first(
            "voice_text",
            {"transcript_text": "asset_text", "prompt_text": "legacy_text", "note": "n"},
        )
        self.assertEqual(text, "voice_text")
        self.assertEqual(src, "voice.prompt_text")

        text2, src2 = resolve_prompt_text_voice_first("", {"transcript_text": "asset_text"})
        self.assertEqual(text2, "asset_text")
        self.assertEqual(src2, "asset.transcript_text")


if __name__ == "__main__":
    unittest.main()
