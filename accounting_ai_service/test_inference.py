import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

import inference


class InferenceServiceTests(unittest.TestCase):
    def setUp(self):
        inference.USER_MEMORY.clear()

    def test_normalizes_spoken_arabic_before_analysis(self):
        self.assertEqual(inference.normalize_user_question_text("  وريني   التقرير؟؟ "), "اعرض التقرير؟")
        self.assertEqual(inference.normalize_user_question_text("حل الوضع المالي"), "حلل الوضع المالي")
        self.assertEqual(inference._analyze_question("ابحث في النت عن ضريبة القيمة المضافة")["asks_web"], True)

    @patch("inference.requests.get")
    def test_web_research_uses_open_sources_before_local_fallback(self, requests_get):
        duck = Mock()
        duck.status_code = 200
        duck.json.return_value = {
            "Heading": "VAT",
            "AbstractText": "Value-added tax is a consumption tax.",
            "AbstractURL": "https://example.test/vat",
        }
        wiki = Mock()
        wiki.status_code = 200
        wiki.json.return_value = {
            "title": "VAT",
            "extract": "VAT is charged on goods and services.",
            "content_urls": {"desktop": {"page": "https://wikipedia.test/vat"}},
        }
        openalex = Mock()
        openalex.status_code = 200
        openalex.json.return_value = {"results": []}
        requests_get.side_effect = [duck, wiki, openalex]

        answer = inference.ask("ابحث في النت عن VAT", max_new_tokens=120)

        self.assertIn("الخلاصة", answer)
        self.assertIn("روابط التحقق", answer)
        self.assertIn("https://example.test/vat", answer)

    def test_remembers_user_information_in_service_session(self):
        saved = inference.ask("تذكر أن العميل المفضل عندي هو شركة النور")
        recalled = inference.ask("ما الذي تعرفه عني؟")

        self.assertIn("تم حفظ", saved)
        self.assertIn("شركة النور", recalled)

    def test_incomplete_model_directory_does_not_break_service(self):
        model = inference.PrivateAccountingModel(Path(__file__).resolve().parent / "models" / "my_model")
        self.assertIsNone(model.model)
        self.assertIsNone(model.tokenizer)

    def test_assistant_identity_is_jameel(self):
        self.assertEqual(inference.MODEL_NAME, "جميل")
        self.assertIn("أنا جميل", inference.ask("إيش اسمك؟"))
        self.assertIn("خدمة الذكاء الاصطناعي", inference.ask("أين أنت؟"))

    def test_general_geography_fallback_answers_capitals(self):
        self.assertIn("الخرطوم", inference.ask("ما هي عاصمة السودان"))
        kazakhstan = inference.ask("ما عاصمة كازاخستان وأين تقع؟")
        self.assertIn("أستانا", kazakhstan)
        self.assertIn("آسيا", kazakhstan)

    def test_jameel_chat_keeps_composer_inside_viewport(self):
        template = (Path(__file__).resolve().parent / "templates" / "jameel.html").read_text(encoding="utf-8")
        self.assertIn("height:100dvh", template)
        self.assertIn("grid-template-rows:72px minmax(0,1fr) auto", template)
        self.assertIn("#messages{min-height:0;overflow-y:auto", template)
        self.assertIn("main{min-width:0;min-height:0;overflow:hidden", template)


if __name__ == "__main__":
    unittest.main()
