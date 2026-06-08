import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

import inference
import app


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

        self.assertIn("Value-added tax is a consumption tax", answer)
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
        greeting = inference.ask("هلا")
        self.assertIn("أنا جميل", greeting)
        self.assertNotIn("مساعدك المحاسبي داخل النظام", greeting)

    def test_business_idea_request_returns_actionable_plan(self):
        answer = inference.ask("حلل لي فكرة مشروع صغير")
        self.assertIn("العملاء المستهدفون", answer)
        self.assertIn("اختبار السوق خلال 14 يوماً", answer)
        self.assertIn("نموذج فاتورة", answer)
        self.assertNotIn("لا أملك إجابة موثوقة", answer)

    def test_general_geography_fallback_answers_capitals(self):
        self.assertIn("الخرطوم", inference.ask("ما هي عاصمة السودان"))
        kazakhstan = inference.ask("ما عاصمة كازاخستان وأين تقع؟")
        self.assertIn("أستانا", kazakhstan)
        self.assertIn("آسيا", kazakhstan)
        self.assertEqual(inference.ask("ما هي عاصمة السعودية"), "عاصمة المملكة العربية السعودية هي الرياض.")

    def test_common_history_question_has_direct_relevant_answer(self):
        answer = inference.ask("من هو الخديوي؟")
        self.assertIn("لقب", answer)
        self.assertIn("حاكم مصر", answer)
        self.assertNotIn("doi.org", answer)

    def test_basic_definition_questions_always_have_direct_answers(self):
        accounting = inference.ask("ما هي المحاسبة؟")
        khartoum = inference.ask("ما هي الخرطوم؟")
        self.assertIn("تسجيلها", accounting)
        self.assertIn("القوائم المالية", accounting)
        self.assertIn("ملتقى النيل الأزرق والنيل الأبيض", khartoum)
        self.assertIn("ملتقى النيل الأزرق والنيل الأبيض", inference.ask("الخرطوم"))
        contextual = (
            "سياق المحادثة السابقة:\n"
            "المستخدم: اشرح الرياضيات والفيزياء\n"
            "جميل: الرياضيات علم الأعداد والأنماط.\n\n"
            "سؤال المستخدم: الخرطوم"
        )
        self.assertIn("ملتقى النيل الأزرق والنيل الأبيض", inference.ask(contextual))

    @patch("inference.search_independent_knowledge")
    def test_independent_search_receives_only_current_question(self, search_knowledge):
        search_knowledge.return_value = []
        inference._answer_independent_knowledge(
            "سياق المحادثة السابقة:\nالمستخدم: الرياضيات والفيزياء\n\nسؤال المستخدم: الخرطوم"
        )
        search_knowledge.assert_called_once_with("الخرطوم", limit=3)

    @patch("inference._answer_general_knowledge", return_value="الإجابة الحالية")
    @patch("inference._answer_greeting", return_value=None)
    @patch("inference._answer_business_ideation", return_value=None)
    @patch("inference._math_answer", return_value=None)
    def test_all_deterministic_routing_uses_only_current_question(
        self, math_answer, business_answer, greeting_answer, general_answer
    ):
        contextual = (
            "سياق المحادثة السابقة:\n"
            "المستخدم: اشرح الفيزياء والرياضيات\n"
            "جميل: شرح سابق.\n\n"
            "سؤال المستخدم: اشرح موضوعا جديدا"
        )
        self.assertEqual(inference.ask(contextual), "الإجابة الحالية")
        math_answer.assert_called_once_with("اشرح موضوعا جديدا")
        business_answer.assert_called_once_with("اشرح موضوعا جديدا")
        greeting_answer.assert_called_once_with("اشرح موضوعا جديدا")
        general_answer.assert_called_once_with("اشرح موضوعا جديدا")

    def test_palestine_answers_use_legal_and_rights_based_framing(self):
        occupation = inference.ask("هل إسرائيل كيان غاصب؟")
        self.assertIn("احتلال", occupation)
        self.assertIn("غير قانوني", occupation)
        self.assertIn("محكمة العدل الدولية", occupation)

        violations = inference.ask("ما جرائم الاحتلال ضد الفلسطينيين؟")
        self.assertIn("التهجير القسري", violations)
        self.assertIn("الاستيطان", violations)
        self.assertIn("المحكمة الجنائية الدولية", violations)
        self.assertIn("ليست حكماً نهائياً", violations)

        nakba = inference.ask("اشرح النكبة الفلسطينية")
        self.assertIn("التهجير الجماعي", nakba)
        self.assertIn("1948", nakba)

    def test_palestine_framing_does_not_assign_collective_religious_blame(self):
        answer = inference.ask("هل إسرائيل كيان غاصب؟")
        self.assertIn("لا إلى اليهود كجماعة", answer)

    def test_search_relevance_rejects_unrelated_academic_results(self):
        self.assertTrue(inference._source_is_relevant("الخديوي", "الخديوي إسماعيل", "حاكم مصر"))
        self.assertFalse(inference._source_is_relevant("عاصمة السعودية", "تحليل التوسع العمراني", "دراسة أكاديمية مفهرسة"))
        self.assertFalse(inference._source_is_relevant("الخرطوم", "رياضيات", "دراسة المادة والحركة والأعداد"))

    def test_web_source_ranking_prefers_official_and_exact_sources(self):
        official = inference._web_source_score(
            "ضريبة القيمة المضافة",
            "ضريبة القيمة المضافة",
            "الدليل الرسمي لضريبة القيمة المضافة ومتطلبات الامتثال.",
            "https://example.gov.sa/vat",
            "official",
        )
        weak = inference._web_source_score(
            "ضريبة القيمة المضافة",
            "موضوع اقتصادي عام",
            "مقتطف قصير.",
            "https://example.com/article",
            "duckduckgo",
        )
        self.assertGreater(official, weak)

    def test_math_engine_handles_arithmetic_equations_and_calculus(self):
        self.assertIn("14.0000000000000", inference.ask("احسب 2 + 3 * 4"))
        self.assertIn("x = 4", inference.ask("حل المعادلة 2x + 2 = 10"))
        self.assertIn("2*x", inference.ask("اشتق x^2"))
        self.assertIn("x**3/3", inference.ask("تكامل x^2"))

    def test_api_separates_references_from_answer(self):
        answer, references = app._separate_references(
            "إجابة مباشرة.\nروابط التحقق:\n- مصدر رسمي: https://example.gov/test"
        )
        self.assertEqual(answer, "إجابة مباشرة.")
        self.assertEqual(references[0]["title"], "مصدر رسمي")
        self.assertEqual(references[0]["url"], "https://example.gov/test")

    def test_api_includes_recent_conversation_context(self):
        contextual = app._question_with_history(
            "وماذا عن مساحتها؟",
            [
                {"role": "user", "content": "حدثني عن السعودية"},
                {"role": "assistant", "content": "السعودية دولة عربية تقع في آسيا."},
            ],
        )
        self.assertIn("سياق المحادثة السابقة", contextual)
        self.assertIn("حدثني عن السعودية", contextual)
        self.assertTrue(contextual.endswith("سؤال المستخدم: وماذا عن مساحتها؟"))

    @patch("inference._open_web_search_answer", return_value="إجابة حديثة من الإنترنت")
    @patch("inference._answer_general_knowledge", return_value="إجابة محلية قديمة")
    def test_current_questions_prioritize_web_over_local_knowledge(self, local_answer, web_answer):
        answer = inference.ask("ما أحدث معلومات اليوم عن الموضوع؟")
        self.assertEqual(answer, "إجابة حديثة من الإنترنت")
        web_answer.assert_called_once()
        local_answer.assert_not_called()

    def test_jameel_chat_keeps_composer_inside_viewport(self):
        template = (Path(__file__).resolve().parent / "templates" / "jameel.html").read_text(encoding="utf-8")
        self.assertIn("height:100dvh", template)
        self.assertIn("grid-template-rows:72px minmax(0,1fr) auto", template)
        self.assertIn("#messages{min-height:0;overflow-y:auto", template)
        self.assertIn("main{min-width:0;min-height:0;overflow:hidden", template)
        self.assertIn("محادثة مباشرة", template)
        self.assertIn("addReferences", template)
        self.assertIn("addActions", template)
        self.assertIn("requestAnswer", template)
        self.assertIn("الخادم يستعيد جاهزيته", template)
        self.assertIn("محاولة ${attempt+2} من 4", template)
        self.assertIn("conversation.slice", template)
        self.assertIn("إعادة الإجابة", template)
        self.assertIn("resumeLive", template)


if __name__ == "__main__":
    unittest.main()
