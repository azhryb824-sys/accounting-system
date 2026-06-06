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

        self.assertIn("نتيجة بحث مفتوح", answer)
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


if __name__ == "__main__":
    unittest.main()
