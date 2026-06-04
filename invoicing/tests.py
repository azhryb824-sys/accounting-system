import json
from io import StringIO
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Branch, Company
from invoicing.models import AIInteractionLearning, AIKnowledgeEntry, AIKnowledgeSource, Customer, Invoice, InvoiceItem, Item, PurchaseInvoice, PurchaseItem, Quote, QuoteItem, Supplier, Tax
from invoicing.ai_services import _polish_answer, analyze_and_route_user_request, answer_financial_question, handle_ai_management_command, normalize_user_question_text, record_ai_interaction_learning
from invoicing.purchase_views import post_purchase_invoice
from invoicing.views import post_sales_invoice


class InvoiceAccountingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester", password="pass")
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.company = Company.objects.create(name="Test Co", unified_number="200")
        self.branch = Branch.objects.create(company=self.company, name="Main")
        self.tax = Tax.objects.create(name="VAT", rate=Decimal("15.00"))
        self.item = Item.objects.create(
            branch=self.branch,
            name="Item",
            quantity=Decimal("10.00"),
            cost=Decimal("20.00"),
            selling_price=Decimal("50.00"),
        )

    def test_pos_terminal_and_lookup_pages_render(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["branch_id"] = self.branch.id
        session["company_id"] = self.company.id
        session.save()

        terminal_response = self.client.get("/invoicing/pos/")
        lookup_response = self.client.get("/invoicing/pos/product/", {"q": "Item"})

        self.assertEqual(terminal_response.status_code, 200)
        self.assertEqual(lookup_response.status_code, 200)
        self.assertTrue(lookup_response.json()["ok"])

    def test_pos_terminal_requires_selected_company_and_branch(self):
        self.client.force_login(self.user)

        response = self.client.get("/invoicing/pos/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/select/", response["Location"])

    def test_ai_management_command_asks_for_missing_item_data_then_creates(self):
        first = handle_ai_management_command(self.branch.id, "أضف صنف باسم قلم بسعر 3 كمية 10")
        self.assertIsNotNone(first.get("pending"))
        self.assertIn("تكلفة", first["answer"])

        second = handle_ai_management_command(self.branch.id, "2", pending=first["pending"])

        self.assertIsNone(second.get("pending"))
        self.assertTrue(Item.objects.filter(branch=self.branch, name="قلم").exists())

    def test_ai_management_command_can_create_employee_and_advance(self):
        employee_result = handle_ai_management_command(self.branch.id, "أضف موظف باسم أحمد براتب 5000")
        self.assertIsNone(employee_result.get("pending"))
        self.assertTrue(employee_result["ok"])
        self.assertTrue(self.company.employees.filter(name__icontains="أحمد").exists())

        advance_result = handle_ai_management_command(self.branch.id, "أضف سلفة للموظف أحمد بمبلغ 700")

        self.assertIsNone(advance_result.get("pending"))
        self.assertTrue(self.company.employee_advances.filter(amount=Decimal("700")).exists())

    def test_ai_can_answer_precise_sales_invoice_details(self):
        customer = Customer.objects.create(name="Customer")
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="S-DETAIL-1",
            invoice_type="standard",
            customer=customer,
            total_amount=Decimal("100.00"),
            total_vat=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
            payment_method="نقدي",
        )
        InvoiceItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            item=self.item,
            description="Item",
            quantity=Decimal("2.00"),
            unit_price=Decimal("50.00"),
            tax=self.tax,
            line_total=Decimal("100.00"),
            line_vat=Decimal("15.00"),
            line_total_with_vat=Decimal("115.00"),
        )

        result = answer_financial_question(self.branch.id, "ما تفاصيل فاتورة بيع S-DETAIL-1؟")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "accounting_data")
        self.assertIn("S-DETAIL-1", result["answer"])
        self.assertIn("115.00", result["answer"])

    def test_ai_answers_user_company_count_from_system_data(self):
        Company.objects.create(name="Second Co", unified_number="201")

        result = answer_financial_question(self.branch.id, "كم عدد الشركات في حسابي", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "accounting_data")
        self.assertIn("عدد الشركات المتاحة في حسابك", result["answer"])
        self.assertIn("2", result["answer"])
        self.assertIn("هذه المعلومة من بيانات النظام", result["answer"])

    def test_ai_pos_checkout_requires_confirmation_then_posts_accounting(self):
        draft = analyze_and_route_user_request(self.branch.id, "بيع 2 Item كاشير", user=self.user)

        self.assertTrue(draft["ok"])
        self.assertIsNotNone(draft.get("pending"))
        self.assertEqual(Invoice.objects.count(), 0)

        confirmed = analyze_and_route_user_request(self.branch.id, "تأكيد", pending=draft["pending"], user=self.user)

        self.assertTrue(confirmed["ok"])
        invoice = Invoice.objects.get(invoice_number__startswith="AI-POS-")
        self.assertTrue(invoice.is_posted)
        self.assertIsNotNone(invoice.journal_entry_id)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal("8.00"))

    def test_ai_quote_requires_confirmation_then_creates_pdf_ready_quote(self):
        draft = analyze_and_route_user_request(self.branch.id, "أنشئ عرض سعر للعميل أحمد 2 Item", user=self.user)

        self.assertTrue(draft["ok"])
        self.assertEqual(draft["source"], "ai_quote")
        self.assertIsNotNone(draft.get("pending"))
        self.assertEqual(Quote.objects.count(), 0)

        confirmed = analyze_and_route_user_request(self.branch.id, "تأكيد", pending=draft["pending"], user=self.user)

        self.assertTrue(confirmed["ok"])
        quote = Quote.objects.get(quote_number__startswith="Q-AI-")
        self.assertEqual(quote.items.count(), 1)
        self.assertEqual(quote.total_with_vat, Decimal("115.0000"))
        self.assertIn("/invoicing/quotes/", confirmed["action"]["url"])

    def test_quote_pdf_download_returns_pdf(self):
        customer = Customer.objects.create(name="عميل PDF")
        quote = Quote.objects.create(
            branch=self.branch,
            quote_number="Q-PDF-1",
            customer=customer,
            total_amount=Decimal("100.00"),
            total_vat=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
        )
        QuoteItem.objects.create(
            branch=self.branch,
            quote=quote,
            item=self.item,
            description="منتج عربي",
            quantity=Decimal("2.00"),
            unit_price=Decimal("50.00"),
            tax_rate=Decimal("15.00"),
            line_total=Decimal("100.00"),
            line_vat=Decimal("15.00"),
            line_total_with_vat=Decimal("115.00"),
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["branch_id"] = self.branch.id
        session["company_id"] = self.company.id
        session.save()

        response = self.client.get(f"/invoicing/quotes/{quote.id}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    @patch("invoicing.ai_services._openalex_research")
    @patch("invoicing.ai_services._wikidata_facts")
    @patch("invoicing.ai_services._wikipedia_summary")
    @patch("invoicing.ai_services._duckduckgo_web_search", return_value=[])
    def test_general_question_uses_free_trusted_web_sources(self, duckduckgo, wikipedia, wikidata, openalex):
        wikipedia.return_value = {
            "title": "IFRS",
            "extract": "معايير التقارير المالية الدولية هي معايير محاسبية دولية.",
            "source_url": "https://example.com/ifrs",
            "source_name": "Wikipedia",
            "license": "CC BY-SA",
        }
        wikidata.return_value = {
            "title": "IFRS",
            "extract": "مجموعة معايير لإعداد التقارير المالية.",
            "source_url": "https://example.com/wikidata-ifrs",
            "source_name": "Wikidata",
            "license": "CC0",
        }
        openalex.return_value = [{
            "title": "IFRS adoption research",
            "extract": "بحث داعم مفهرس في OpenAlex.",
            "source_url": "https://example.com/openalex-ifrs",
            "source_name": "OpenAlex",
            "license": "CC0",
        }]

        result = answer_financial_question(self.branch.id, "ما هو IFRS؟")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "free_web")
        self.assertIn("IFRS", result["answer"])
        self.assertIn("https://example.com/openalex-ifrs", result["answer"])
        self.assertNotIn("بحثت", result["answer"])
        self.assertNotIn("CC0", result["answer"])
        self.assertIn("توضيح مهني", result["answer"])
        self.assertIn("درجة الاعتماد", result["answer"])

    @patch("invoicing.ai_services._openalex_research")
    @patch("invoicing.ai_services._wikidata_facts")
    @patch("invoicing.ai_services._wikipedia_summary")
    @patch("invoicing.ai_services._duckduckgo_web_search", return_value=[])
    def test_scientific_question_uses_free_web_sources(self, duckduckgo, wikipedia, wikidata, openalex):
        wikipedia.return_value = {
            "title": "Photosynthesis",
            "extract": "التمثيل الضوئي عملية تستخدم فيها النباتات الضوء لإنتاج الطاقة.",
            "source_url": "https://example.com/photosynthesis",
            "source_name": "Wikipedia",
            "license": "CC BY-SA",
        }
        wikidata.return_value = {}
        openalex.return_value = []

        result = answer_financial_question(self.branch.id, "اشرح لي التمثيل الضوئي علميا")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "free_web")
        self.assertIn("Photosynthesis", result["answer"])
        self.assertIn("https://example.com/photosynthesis", result["answer"])
        self.assertNotIn("Wikipedia", result["answer"])
        self.assertNotIn("الخطوة التالية المقترحة", result["answer"])

    @patch("invoicing.ai_services._openalex_research")
    @patch("invoicing.ai_services._wikidata_facts")
    @patch("invoicing.ai_services._wikipedia_summary")
    @patch("invoicing.ai_services._duckduckgo_web_search")
    def test_research_request_gets_professional_source_analysis(self, duckduckgo, wikipedia, wikidata, openalex):
        duckduckgo.return_value = [{
            "title": "AI overview",
            "extract": "نتيجة ويب عامة عن الذكاء الاصطناعي.",
            "source_url": "https://example.com/web-ai",
            "source_name": "DuckDuckGo Web Search",
            "license": "web",
        }]
        wikipedia.return_value = {
            "title": "Artificial intelligence",
            "extract": "الذكاء الاصطناعي مجال يبني أنظمة قادرة على أداء مهام تتطلب عادة ذكاء بشريا.",
            "source_url": "https://example.com/ai",
            "source_name": "Wikipedia",
            "license": "CC BY-SA",
        }
        wikidata.return_value = {}
        openalex.return_value = [{
            "title": "AI research review",
            "extract": "مرجع بحثي داعم عن تطبيقات الذكاء الاصطناعي.",
            "source_url": "https://openalex.org/W123",
            "source_name": "OpenAlex",
            "license": "CC0",
        }]

        result = answer_financial_question(self.branch.id, "ابحث في النت عن الذكاء الاصطناعي وحلل المعلومات")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "free_web")
        self.assertIn("الخلاصة", result["answer"])
        self.assertIn("توضيح مهني", result["answer"])
        self.assertIn("مراجع مختصرة للتحقق", result["answer"])
        self.assertNotIn("بحثت", result["answer"])
        self.assertNotIn("المصادر والتراخيص", result["answer"])

    @patch("invoicing.ai_services._openalex_research")
    @patch("invoicing.ai_services._wikidata_facts")
    @patch("invoicing.ai_services._wikipedia_summary")
    @patch("invoicing.ai_services._duckduckgo_web_search", return_value=[])
    def test_latest_questions_include_current_source_warning(self, duckduckgo, wikipedia, wikidata, openalex):
        wikipedia.return_value = {
            "title": "Python",
            "extract": "بايثون لغة برمجة عالية المستوى.",
            "source_url": "https://example.com/python",
            "source_name": "Wikipedia",
            "license": "CC BY-SA",
        }
        wikidata.return_value = {}
        openalex.return_value = []

        result = answer_financial_question(self.branch.id, "ما أحدث إصدار من Python؟")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "free_web")
        self.assertIn("حديثا أو سريع التغير", result["answer"])
        self.assertIn("الجهة الرسمية الأحدث", result["answer"])

    def test_ai_quote_draft_has_single_confirmation_instruction(self):
        result = analyze_and_route_user_request(self.branch.id, "أنشئ عرض سعر للعميل أحمد 2 Item", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "ai_quote")
        self.assertEqual(result["answer"].count("تأكيد"), 1)
        self.assertEqual(result["answer"].count("إلغاء"), 1)

    def test_ai_uses_auto_updated_local_knowledge_entries(self):
        source = AIKnowledgeSource.objects.create(
            name="Trusted source",
            url="https://example.com/source",
            license_note="test",
        )
        AIKnowledgeEntry.objects.create(
            source=source,
            title="Inventory turnover",
            summary="Inventory turnover measures how fast stock is sold and replaced.",
            source_url="https://example.com/inventory-turnover",
            topic="inventory",
            content_hash="inventory-turnover-test",
        )

        result = answer_financial_question(self.branch.id, "اشرح inventory turnover")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_knowledge")
        self.assertIn("Inventory turnover", result["answer"])
        self.assertIn("وفق المعرفة المتاحة داخل النظام", result["answer"])
        self.assertNotIn("https://example.com/inventory-turnover", result["answer"])

    def test_ai_remembers_explicit_user_information(self):
        result = {"source": "local", "answer": "تم"}

        record_ai_interaction_learning(
            self.branch.id,
            self.user,
            "تذكر: العميل المفضل عندي هو شركة النور",
            result,
        )
        answer = answer_financial_question(self.branch.id, "ما هو العميل المفضل عندي؟", user=self.user)

        self.assertTrue(AIKnowledgeEntry.objects.filter(source_url="app://user-memory").exists())
        self.assertEqual(answer["source"], "local_knowledge")
        self.assertIn("شركة النور", answer["answer"])

    @patch("invoicing.management.commands.update_ai_knowledge.requests.get")
    def test_update_ai_knowledge_loads_multiple_public_sources(self, requests_get):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        def fake_get(url, **kwargs):
            if "wikipedia" in url:
                return FakeResponse({"query": {"search": [{"title": "Accounting", "snippet": "Accounting summary."}]}})
            if "wikidata" in url:
                return FakeResponse({"search": [{"label": "Accounting", "description": "structured finance concept", "id": "Q4116214"}]})
            if "openalex" in url:
                return FakeResponse({"results": [{"title": "Accounting systems research", "publication_year": 2024, "cited_by_count": 10, "id": "https://openalex.org/W1"}]})
            return FakeResponse({})

        requests_get.side_effect = fake_get
        out = StringIO()

        call_command("update_ai_knowledge", topic=["retail analytics"], limit=1, stdout=out)

        self.assertTrue(AIKnowledgeSource.objects.filter(name="Wikipedia summaries").exists())
        self.assertTrue(AIKnowledgeSource.objects.filter(name="Wikidata public facts").exists())
        self.assertTrue(AIKnowledgeSource.objects.filter(name="OpenAlex research index").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="Accounting systems research").exists())
        self.assertIn("AI knowledge updated", out.getvalue())

    def test_seed_ai_training_loads_curated_local_guidance(self):
        out = StringIO()

        call_command("seed_ai_training", stdout=out)

        self.assertTrue(AIKnowledgeSource.objects.filter(url="app://curated-ai-training").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="متى يستخدم المساعد البحث في النت").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="تدريب الرياضيات").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="تدريب اللغة العربية").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="تدريب اللغة الإنجليزية").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="تدريب علوم الفلك").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="تدريب الهندسة").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="تدريب العلوم المحاسبية").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="تدريب الفيزياء").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="أسلوب الحل خطوة بخطوة").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="أسلوب البحث الموثق").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="رياضيات موسعة: التفاضل والتكامل والإحصاء").exists())
        self.assertTrue(AIKnowledgeEntry.objects.filter(title="المحاسبة موسعة: التحليل والرقابة").exists())
        result = answer_financial_question(self.branch.id, "متى تبحث في النت؟", user=self.user)
        self.assertEqual(result["source"], "local_knowledge")
        self.assertIn("المصادر المفتوحة", result["answer"])
        self.assertIn("Seeded", out.getvalue())

    def test_ai_interaction_learning_stores_summary_only(self):
        record = record_ai_interaction_learning(
            self.branch.id,
            self.user,
            "سؤال طويل فيه رقم 0555555555 وبريد test@example.com",
            {"source": "free_web", "answer": "full answer should not be stored"},
        )

        self.assertIsNotNone(record)
        stored = AIInteractionLearning.objects.get(id=record.id)
        self.assertIn("[number]", stored.question_summary)
        self.assertIn("[email]", stored.question_summary)
        self.assertNotIn("full answer", stored.improvement_note)
        self.assertEqual(stored.answer_source, "free_web")

    def test_ai_refuses_islamic_law_questions_and_refers_to_scholars(self):
        result = answer_financial_question(self.branch.id, "ما حكم المرابحة في الشريعة الإسلامية؟")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "islamic_policy")
        self.assertIn("لا أستطيع تقديم فتوى", result["answer"])
        self.assertIn("أهل العلم", result["answer"])

    def test_profit_word_does_not_trigger_islamic_policy_guard(self):
        result = answer_financial_question(self.branch.id, "حلل الأرباح والمنتجات")

        self.assertTrue(result["ok"])
        self.assertNotEqual(result["source"], "islamic_policy")

    def test_calculate_without_numbers_asks_for_numbers_not_joke(self):
        result = answer_financial_question(self.branch.id, "احسب")

        self.assertTrue(result["ok"])
        self.assertIn("الأرقام", result["answer"])
        self.assertNotIn("ابتسامة", result["answer"])
        self.assertNotIn("المحاسب لا يخاف", result["answer"])

    def test_ai_calculates_basic_math_locally(self):
        result = answer_financial_question(self.branch.id, "احسب 1500 + 375")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_calculator")
        self.assertIn("1875", result["answer"])

    def test_ai_calculates_vat_locally(self):
        result = answer_financial_question(self.branch.id, "احسب ضريبة 15% على 2000")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_calculator")
        self.assertIn("300", result["answer"])

    def test_simple_general_fact_does_not_trigger_financial_analysis(self):
        result = answer_financial_question(self.branch.id, "كم عدد أيام الأسبوع؟", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local")
        self.assertIn("سبعة أيام", result["answer"])
        self.assertNotIn("تحليل مالي", result["answer"])
        self.assertNotIn("الفترة", result["answer"])

    def test_short_ambiguous_command_gets_clarification(self):
        result = answer_financial_question(self.branch.id, "حلل")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "clarification")
        self.assertIn("أمثلة", result["answer"])

    @patch("invoicing.ai_services._model_answer_financial_question")
    def test_greeting_is_answered_locally_without_financial_analysis(self, model_answer):
        result = answer_financial_question(self.branch.id, "أهلا", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local")
        self.assertEqual(result["intent"], "conversation")
        self.assertEqual(result["confidence"], "medium")
        self.assertIn("أهلا", result["answer"])
        self.assertNotIn("تحليل احترافي", result["answer"])
        model_answer.assert_not_called()

    @patch("invoicing.ai_services._model_answer_financial_question")
    def test_assistant_route_repairs_irrelevant_greeting_answer(self, model_answer):
        model_answer.return_value = {
            "ok": True,
            "source": "local_strong",
            "answer": "تحليل احترافي مبني على بيانات النظام:\n\nالملخص التنفيذي:\n- المبيعات: 0.00",
            "context": {},
        }

        result = analyze_and_route_user_request(self.branch.id, "أهلا", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local")
        self.assertEqual(result["action"]["type"], "answer")
        self.assertIn("أهلا", result["answer"])
        self.assertNotIn("تحليل احترافي", result["answer"])

    def test_ai_normalizes_spoken_and_dialect_question_text_before_analysis(self):
        self.assertEqual(normalize_user_question_text("  وريني   التقرير؟؟  "), "اعرض التقرير؟")
        self.assertEqual(normalize_user_question_text("حل الوضع المالي"), "حلل الوضع المالي")
        self.assertEqual(normalize_user_question_text("ابغى افتح الفاتوره"), "أريد افتح الفاتورة")

    def test_spoken_navigation_request_is_analyzed_before_answering(self):
        result = analyze_and_route_user_request(self.branch.id, "وريني التقرير", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["question_analysis"]["normalized_text"], "اعرض التقرير")
        self.assertTrue(result["question_analysis"]["asks_execution"])
        self.assertEqual(result["action"]["type"], "navigate")

    @patch("invoicing.ai_services.free_web_general_answer", return_value="")
    @patch("invoicing.ai_services._private_ai_request", return_value={"ok": False, "text": ""})
    def test_spoken_analysis_request_uses_normalized_accounting_intent(self, private_ai, web_answer):
        result = answer_financial_question(self.branch.id, "حل الوضع المالي", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["intent"], "accounting_analysis")
        self.assertTrue(result["question_analysis"]["asks_company_data"])
        self.assertIn("الملخص", result["answer"])

    @patch("invoicing.ai_services.free_web_general_answer", return_value="")
    @patch("invoicing.ai_services._private_ai_request")
    def test_explanation_question_does_not_trigger_navigation(self, private_ai, web_answer):
        private_ai.return_value = {"ok": True, "text": "القيد المحاسبي يسجل أثر العملية في طرف مدين وطرف دائن."}

        result = analyze_and_route_user_request(self.branch.id, "اشرح لي القيد المحاسبي", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["intent"], "explanation")
        self.assertEqual(result["action"]["type"], "answer")
        self.assertIn("طرف مدين وطرف دائن", result["answer"])
        self.assertNotIn("سأفتح الصفحة المناسبة", result["answer"])

    @patch("invoicing.ai_services.free_web_general_answer", return_value="")
    @patch("invoicing.ai_services._answer_precise_accounting_question", return_value="")
    @patch("invoicing.ai_services._private_ai_request")
    def test_private_short_answer_gets_quality_notice(self, private_ai, precise_answer, web_answer):
        private_ai.return_value = {"ok": True, "text": "راجع العملاء المتأخرين وابدأ بالأكبر قيمة ثم الأقدم استحقاقا."}

        result = answer_financial_question(self.branch.id, "ما أفضل إجراء لتحسين التحصيل؟", user=self.user)

        self.assertTrue(result["ok"])
        self.assertIn("confidence", result)
        self.assertIn("intent", result)
        self.assertIn("ملاحظة جودة", result["answer"])

    @patch("invoicing.ai_services.free_web_general_answer", return_value="")
    @patch("invoicing.ai_services._answer_precise_accounting_question", return_value="")
    @patch("invoicing.ai_services._private_ai_request")
    def test_weak_private_ai_answer_uses_strong_local_fallback(self, private_ai, precise_answer, web_answer):
        private_ai.return_value = {"ok": True, "text": "لا أملك معلومات كافية"}

        result = answer_financial_question(self.branch.id, "قيّم أداء الفرع ماليا", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_strong")
        self.assertIn("الملخص", result["answer"])
        self.assertNotIn("لا أملك معلومات كافية", result["answer"])

    def test_zatca_regulation_questions_use_official_index(self):
        result = answer_financial_question(self.branch.id, "زودني بجميع لوائح هيئة الزكاة والضريبة والجمارك")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "zatca_regulations")
        self.assertIn("zatca.gov.sa", result["answer"])
        self.assertIn("هيئة الزكاة والضريبة والجمارك هي الجهة الحكومية", result["answer"])
        self.assertNotIn("تم ربط إجابة الذكاء الاصطناعي", result["answer"])
        self.assertIn("الفوترة الإلكترونية", result["answer"])
        self.assertIn("ضريبة القيمة المضافة", result["answer"])

    def test_ai_estimates_profit_for_adding_product_quantity(self):
        customer = Customer.objects.create(name="Customer")
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="S-PROFIT-1",
            invoice_type="standard",
            customer=customer,
            total_amount=Decimal("250.00"),
            total_vat=Decimal("37.50"),
            total_with_vat=Decimal("287.50"),
            payment_method="نقدي",
        )
        InvoiceItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            item=self.item,
            description="Item",
            quantity=Decimal("5.00"),
            unit_price=Decimal("50.00"),
            tax=self.tax,
            line_total=Decimal("250.00"),
            line_vat=Decimal("37.50"),
            line_total_with_vat=Decimal("287.50"),
        )

        result = answer_financial_question(self.branch.id, "إذا أضفت 500 حبة من Item كم متوقع تزيد الأرباح؟")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "accounting_data")
        self.assertIn("500", result["answer"])
        self.assertIn("15000.00", result["answer"])
        self.assertIn("ربح الوحدة", result["answer"])

    def test_ai_flags_low_margin_products(self):
        low_item = Item.objects.create(
            branch=self.branch,
            name="LowMargin",
            quantity=Decimal("20.00"),
            cost=Decimal("9.50"),
            selling_price=Decimal("10.00"),
        )
        customer = Customer.objects.create(name="Customer")
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="S-LOW-1",
            invoice_type="standard",
            customer=customer,
            total_amount=Decimal("100.00"),
            total_vat=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
            payment_method="نقدي",
        )
        InvoiceItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            item=low_item,
            description="LowMargin",
            quantity=Decimal("10.00"),
            unit_price=Decimal("10.00"),
            tax=self.tax,
            line_total=Decimal("100.00"),
            line_vat=Decimal("15.00"),
            line_total_with_vat=Decimal("115.00"),
        )

        result = answer_financial_question(self.branch.id, "ما المنتجات ذات الربح المنخفض للتقليل منها؟")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "accounting_data")
        self.assertIn("LowMargin", result["answer"])
        self.assertIn("منخفضة الهامش", result["answer"])

    @patch("invoicing.purchase_views.analyze_and_route_user_request")
    @patch("invoicing.purchase_views.command_from_camera_image")
    def test_ai_assistant_command_merges_screen_analysis_with_user_question(self, camera_reader, analyzer):
        self.client.force_login(self.user)
        session = self.client.session
        session["branch_id"] = self.branch.id
        session["company_id"] = self.company.id
        session.save()
        camera_reader.return_value = {"ok": True, "command": "تظهر فاتورة بيع بإجمالي 115 ريال"}
        analyzer.return_value = {
            "ok": True,
            "answer": "تحليل الشاشة",
            "source": "test",
            "pending": None,
            "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
            "suggestions": [],
            "followups": [],
            "context": {},
        }

        response = self.client.post(
            "/invoicing/purchases/ai/assistant/command/",
            data=json.dumps({
                "command": "ما الخطأ الظاهر؟",
                "image_base64": "abc",
                "media_type": "image/jpeg",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        sent_command = analyzer.call_args.args[1]
        self.assertIn("ما الخطأ الظاهر؟", sent_command)
        self.assertIn("تحليل الشاشة/الصورة", sent_command)
        self.assertIn("تظهر فاتورة بيع", sent_command)

    def test_ai_assistant_page_allows_superuser_without_branch(self):
        self.client.force_login(self.user)

        response = self.client.get("/invoicing/purchases/ai/assistant/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "المحادثة")

    @patch("invoicing.purchase_views.answer_financial_question")
    def test_ai_assistant_command_allows_superuser_without_branch(self, answer_question):
        self.client.force_login(self.user)
        answer_question.return_value = {
            "ok": True,
            "source": "accounting_data",
            "answer": "عدد الشركات المتاحة في حسابك: 1.",
            "context": {},
        }

        response = self.client.post(
            "/invoicing/purchases/ai/assistant/command/",
            data=json.dumps({"command": "كم عدد الشركات في حسابي؟"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        answer_question.assert_called_once()
        self.assertIsNone(answer_question.call_args.args[0])

    def test_ai_assistant_template_has_valid_voice_patterns(self):
        template = Path("invoicing/templates/invoicing/ai_assistant.html").read_text(encoding="utf-8")

        self.assertNotIn("/arabic|???????/i", template)
        self.assertIn("arabic|عربي|العربية", template)
        self.assertIn("mediaUnavailableMessage", template)
        self.assertNotIn("const cleanText = improveSpeechText", template)
        self.assertIn("pronounceArabicNumber", template)
        self.assertIn("keepSpeechPhraseTogether", template)
        self.assertIn("limitSpeechTextByWord", template)
        self.assertIn("addArabicSpeechPauses", template)
        self.assertIn("applyArabicCaseForSpeech", template)
        self.assertIn("normalizeArabicProsodyForSpeech", template)
        self.assertIn("speechProsodyForChunk", template)
        self.assertIn("const maxChunkLength = 170", template)
        self.assertIn("inputSource = 'typed'", template)
        self.assertIn("inputSource === 'voice' || inputSource === 'live'", template)
        self.assertIn("liveConversationMode ? 'live' : 'voice'", template)
        self.assertIn("عَدَدُ أَيَّامِ الأُسْبُوعِ", template)
        self.assertIn("ضَرِيبَةُ القِيمَةِ المُضَافَةِ", template)
        self.assertIn("ضريبة القيمة المضافة", template)
        self.assertIn("المعايير الدولية للتقرير المالي", template)
        self.assertIn("واجهة برمجة التطبيقات", template)

    @patch("invoicing.ai_services.free_web_general_answer")
    @patch("invoicing.ai_services._model_answer_financial_question")
    def test_ai_uses_web_when_model_answer_is_weak(self, model_answer, web_answer):
        model_answer.return_value = {
            "ok": True,
            "source": "private",
            "answer": "I cannot answer this with the available local context.",
            "context": {},
        }
        web_answer.return_value = "Web researched answer with sources."

        result = answer_financial_question(self.branch.id, "latest accounting standards updates", user=self.user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "free_web")
        self.assertIn("Web researched answer", result["answer"])
        web_answer.assert_called_once()

    @patch("invoicing.ai_services._style_variant_index", side_effect=[0, 1])
    def test_ai_varies_style_for_repeated_same_answer(self, variant_index):
        first = _polish_answer("عدد الشركات المتاحة في حسابك: 1.", "كم عدد الشركات في حسابي؟")
        second = _polish_answer("عدد الشركات المتاحة في حسابك: 1.", "كم عدد الشركات في حسابي؟")

        self.assertNotEqual(first, second)
        self.assertIn("عدد الشركات المتاحة", first)
        self.assertIn("عدد الشركات المتاحة", second)
        self.assertEqual(variant_index.call_count, 2)

    def test_sales_invoice_posts_once_and_reduces_inventory_once(self):
        customer = Customer.objects.create(name="Customer")
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="S-1",
            invoice_type="standard",
            customer=customer,
            total_amount=Decimal("100.00"),
            total_vat=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
            payment_method="نقدي",
        )
        InvoiceItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            item=self.item,
            description="Item",
            quantity=Decimal("2.00"),
            unit_price=Decimal("50.00"),
            tax=self.tax,
            line_total=Decimal("100.00"),
            line_vat=Decimal("15.00"),
            line_total_with_vat=Decimal("115.00"),
        )

        first = post_sales_invoice(invoice)
        self.item.refresh_from_db()
        invoice.refresh_from_db()
        second = post_sales_invoice(invoice)

        self.assertEqual(first.id, second.id)
        self.assertEqual(invoice.journal_entry_id, first.id)
        self.assertEqual(self.item.quantity, Decimal("8.00"))
        self.assertEqual(first.total_debit(), first.total_credit())

    def test_purchase_item_creation_does_not_auto_double_inventory(self):
        supplier = Supplier.objects.create(name="Supplier")
        invoice = PurchaseInvoice.objects.create(
            branch=self.branch,
            supplier=supplier,
            invoice_number="P-1",
            issue_date=timezone.localdate(),
            total_before_vat=Decimal("100.00"),
            vat_amount=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
        )

        PurchaseItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            item=self.item,
            quantity=Decimal("3.00"),
            price=Decimal("25.00"),
        )
        self.item.refresh_from_db()

        self.assertEqual(self.item.quantity, Decimal("10.00"))

    def test_purchase_invoice_links_balanced_entry_once(self):
        supplier = Supplier.objects.create(name="Supplier")
        invoice = PurchaseInvoice.objects.create(
            branch=self.branch,
            supplier=supplier,
            invoice_number="P-2",
            issue_date=timezone.localdate(),
            total_before_vat=Decimal("100.00"),
            vat_amount=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
        )

        first = post_purchase_invoice(invoice)
        invoice.refresh_from_db()
        second = post_purchase_invoice(invoice)

        self.assertEqual(first.id, second.id)
        self.assertEqual(invoice.journal_entry_id, first.id)
        self.assertEqual(first.total_debit(), first.total_credit())
