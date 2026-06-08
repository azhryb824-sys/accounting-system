import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))

from intelligence import assess_answer, plan_query, resolve_followup
import app


class IntelligenceLayerTests(unittest.TestCase):
    def test_routes_major_domains_and_intents(self):
        self.assertEqual(plan_query("احسب 18 * 7").intent, "calculate")
        self.assertEqual(plan_query("ما هي الخصوم؟").domain, "accounting")
        self.assertEqual(plan_query("ما عاصمة اليابان؟").domain, "geography")
        self.assertEqual(plan_query("اشرح الطاقة النووية").domain, "science")
        self.assertEqual(plan_query("صغ رسالة إنجليزية").domain, "language")

    def test_detects_freshness_and_complexity(self):
        plan = plan_query("ما أحدث القوانين الحالية لضريبة القيمة المضافة اليوم؟")
        self.assertTrue(plan.needs_web)
        self.assertEqual(plan.domain, "accounting")

    def test_resolves_short_followup_from_last_user_topic(self):
        resolved = resolve_followup(
            "وما مساحتها؟",
            [{"role": "user", "content": "حدثني عن المملكة العربية السعودية"}],
        )
        self.assertEqual(resolved, "ما مساحة المملكة العربية السعودية؟")

    def test_quality_rejects_fallback_and_rewards_grounding(self):
        weak = assess_answer("ما هي الخصوم؟", "لا أملك إجابة موثوقة كافية.")
        strong = assess_answer(
            "ما هي الخصوم؟",
            "الخصوم التزامات مالية مستحقة على المنشأة مثل الموردين والقروض.",
            [{"url": "https://example.test"}],
        )
        self.assertEqual(weak["level"], "low")
        self.assertGreater(strong["score"], weak["score"])

    @patch("app._open_web_search_answer", return_value="إجابة مستردة من بحث موثوق.")
    @patch("app.ask", return_value="لا أملك إجابة موثوقة كافية.")
    def test_api_recovers_low_quality_answer_through_web(self, _ask, _research):
        response = app.ask_question(app.QuestionRequest(question="موضوع غير معروف"))
        self.assertIn("إجابة مستردة", response.answer)
        _research.assert_called_once_with("موضوع غير معروف")


if __name__ == "__main__":
    unittest.main()
