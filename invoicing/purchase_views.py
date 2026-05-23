import json

from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.views.decorators.http import require_POST

from .models import PurchaseInvoice, PurchaseItem, Supplier, Item, StockMovement
from .forms import PurchaseInvoiceForm, ItemForm, AIInvoiceUploadForm
from .ai_services import ai_configuration_status, analyze_and_route_user_request, answer_financial_question, extract_invoice_from_image, generate_financial_insights, match_invoice_items
from django.utils.translation import gettext_lazy as _
from accounts.views import role_required
from core.models import Branch
from core.services.accounting import create_balanced_entry
from core.services.monthly_close import assert_month_open
from decimal import Decimal
from datetime import date


def post_purchase_invoice(invoice):
    if invoice.journal_entry_id:
        return invoice.journal_entry
    assert_month_open(invoice.branch.company, invoice.issue_date)
    entry = create_balanced_entry(
        branch=invoice.branch,
        date=invoice.issue_date,
        description=f"فاتورة شراء رقم {invoice.invoice_number}",
        lines=[
            {"account": "1200", "debit": invoice.total_before_vat, "note": "إضافة مخزون من فاتورة شراء"},
            {"account": "2100", "debit": invoice.vat_amount, "note": "ضريبة مدخلات"},
            {"account": "2200", "credit": invoice.total_with_vat, "note": "مستحق للمورد"},
        ],
    )
    invoice.journal_entry = entry
    invoice.save(update_fields=["journal_entry"])
    return entry

# ============================
#  قائمة فواتير المشتريات حسب الفرع
# ============================
@login_required(login_url='login')
def purchase_list(request):
    branch_id = request.session.get('branch_id')
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id).order_by('-issue_date')

    return render(request, 'invoicing/purchase_list.html', {
        "purchases": purchases, "title": _("Purchase Invoices List")
    })


# ============================
#  إضافة فاتورة مشتريات
# ============================
@login_required(login_url='login')
def purchase_add(request):
    branch_id = request.session.get('branch_id')

    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST)

        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.branch_id = branch_id
            branch = get_object_or_404(Branch, id=branch_id)
            assert_month_open(branch.company, invoice.issue_date)
            invoice.save()

            items = request.POST.getlist("item_id")
            quantities = request.POST.getlist("quantity")
            prices = request.POST.getlist("price")

            for i in range(len(items)):
                purchase_item = PurchaseItem.objects.create(
                    invoice=invoice,
                    branch_id=branch_id,
                    item_id=items[i],
                    quantity=quantities[i],
                    price=prices[i]
                )

                # تحديث كمية المخزون الفعلي للصنف
                item_obj = purchase_item.item
                item_obj.quantity += purchase_item.quantity
                item_obj.save()

                # حركة مخزون IN
                StockMovement.objects.create(
                    branch_id=branch_id,
                    item=purchase_item.item,
                    quantity=purchase_item.quantity,
                    movement_type="IN"
                )

            post_purchase_invoice(invoice)
            messages.success(request, _("Purchase invoice added and inventory updated successfully."))
            return redirect('purchase_list')

    else:
        form = PurchaseInvoiceForm()

    return render(request, 'invoicing/purchase_form.html', {
        "form": form,
        "items": Item.objects.filter(branch_id=branch_id, is_active=True).order_by("name"),
        "title": _("Add Purchase Invoice")
    })


# ============================
#  تعديل فاتورة مشتريات
# ============================
@login_required(login_url='login')
def purchase_edit(request, id):
    purchase = get_object_or_404(PurchaseInvoice, id=id)

    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST, instance=purchase)
        if form.is_valid():
            edited_purchase = form.save(commit=False)
            assert_month_open(edited_purchase.branch.company, edited_purchase.issue_date)
            edited_purchase.save()
            messages.success(request, _("Purchase invoice updated successfully."))
            return redirect('purchase_list')

    else:
        form = PurchaseInvoiceForm(instance=purchase)

    return render(request, 'invoicing/purchase_form.html', {
        "form": form,
        "items": Item.objects.filter(branch_id=request.session.get('branch_id'), is_active=True).order_by("name"),
        "title": _("Edit Purchase Invoice")
    })


# ============================
#  حذف فاتورة مشتريات
# ============================
@login_required(login_url='login')
def purchase_delete(request, id):
    purchase = get_object_or_404(PurchaseInvoice, id=id)
    assert_month_open(purchase.branch.company, purchase.issue_date)
    purchase.delete()
    messages.success(request, _("Purchase invoice deleted successfully."))
    return redirect('purchase_list')

# ============================
#  قائمة المخزون حسب الفرع
# ============================
@login_required(login_url='login')
@role_required('view_item')
def inventory_list(request):
    branch_id = request.session.get('branch_id')
    items = Item.objects.filter(branch_id=branch_id).annotate(inventory_value=F("quantity") * F("cost")).order_by("name")

    return render(request, 'invoicing/inventory_list.html', {
        "items": items, "title": _("Inventory List")
    })


@login_required(login_url='login')
@role_required('add_item')
def item_add(request):
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, id=branch_id)
    form = ItemForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        item.branch = branch
        item.save()
        messages.success(request, "تم إضافة الصنف بنجاح.")
        return redirect('inventory_list')
    return render(request, 'invoicing/item_form.html', {"form": form, "title": "إضافة صنف"})


@login_required(login_url='login')
@role_required('change_item')
def item_edit(request, item_id):
    branch_id = request.session.get('branch_id')
    item = get_object_or_404(Item, id=item_id, branch_id=branch_id)
    form = ItemForm(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "تم تعديل الصنف بنجاح.")
        return redirect('inventory_list')
    return render(request, 'invoicing/item_form.html', {"form": form, "title": "تعديل صنف"})


@login_required(login_url='login')
@role_required('import_ai_invoice')
def ai_invoice_import(request):
    branch_id = request.session.get('branch_id')
    form = AIInvoiceUploadForm(request.POST or None, request.FILES or None)
    result = None
    ai_status = ai_configuration_status()
    if not branch_id:
        messages.warning(request, "اختر الشركة والفرع قبل استخدام إضافة الفاتورة بالذكاء الاصطناعي.")
        return redirect("select_company_branch")
    if request.method == 'POST' and form.is_valid():
        result = extract_invoice_from_image(form.cleaned_data['invoice_image'])
        if result.get("ok"):
            data = result["data"]
            matched_items = match_invoice_items(branch_id, data.get("items", []))
            branch = get_object_or_404(Branch, id=branch_id)
            issue_date = date.fromisoformat(data.get("issue_date"))
            assert_month_open(branch.company, issue_date)
            supplier, _ = Supplier.objects.get_or_create(name=data.get("supplier_name") or "مورد من الذكاء الاصطناعي")
            invoice = PurchaseInvoice.objects.create(
                branch=branch,
                supplier=supplier,
                invoice_number=data.get("invoice_number") or f"AI-{PurchaseInvoice.objects.count() + 1}",
                issue_date=issue_date,
                total_before_vat=Decimal(str(data.get("subtotal") or 0)),
                vat_amount=Decimal(str(data.get("vat") or 0)),
                total_with_vat=Decimal(str(data.get("total") or 0)),
            )
            for row in matched_items:
                item = row["item"]
                if not item:
                    item = Item.objects.create(
                        branch=branch,
                        name=row["source_name"] or "صنف من الفاتورة",
                        cost=row["unit_price"],
                        selling_price=row["unit_price"],
                        quantity=0,
                    )
                purchase_item = PurchaseItem.objects.create(
                    invoice=invoice,
                    branch=branch,
                    item=item,
                    quantity=row["quantity"],
                    price=row["unit_price"],
                )
                item.quantity += purchase_item.quantity
                item.cost = purchase_item.price
                item.save(update_fields=["quantity", "cost"])
                StockMovement.objects.create(branch=branch, item=item, quantity=purchase_item.quantity, movement_type="IN")
            post_purchase_invoice(invoice)
            messages.success(request, "تم استخراج الفاتورة وإضافتها وترحيلها محاسبياً.")
            return redirect("purchase_list")
    return render(request, 'invoicing/ai_invoice_import.html', {
        "form": form,
        "result": result,
        "title": "إضافة فاتورة بالذكاء الاصطناعي",
        "ai_status": ai_status,
    })


@login_required(login_url='login')
@role_required('view_ai_insights')
def ai_insights(request):
    branch_id = request.session.get('branch_id')
    if not branch_id:
        return redirect("select_company_branch")
    low_stock = Item.objects.filter(branch_id=branch_id, quantity__lte=F("min_quantity"), is_active=True).count()
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id).order_by("-issue_date")[:5]
    insights = generate_financial_insights(branch_id)
    return render(request, 'invoicing/ai_insights.html', {
        "title": "نصائح وتوقعات الذكاء الاصطناعي",
        "tips": insights.get("tips", []),
        "insights": insights,
        "purchases": purchases,
        "low_stock": low_stock,
        "ai_status": ai_configuration_status(),
    })


@login_required(login_url='login')
@role_required('view_ai_insights')
def ai_assistant(request):
    branch_id = request.session.get('branch_id')
    if not branch_id:
        return redirect("select_company_branch")
    answer = None
    question = ""
    insights = generate_financial_insights(branch_id)
    if request.method == "POST":
        question = (request.POST.get("question") or "").strip()
        if question:
            answer = answer_financial_question(branch_id, question)
        else:
            messages.warning(request, "اكتب سؤالك أولاً.")
    return render(request, "invoicing/ai_assistant.html", {
        "title": "مساعد الذكاء الاصطناعي",
        "ai_status": ai_configuration_status(),
        "insights": insights,
        "answer": answer,
        "question": question,
    })


@login_required(login_url='login')
@role_required('view_ai_insights')
@require_POST
def ai_assistant_command(request):
    branch_id = request.session.get('branch_id')
    if not branch_id:
        return JsonResponse({"ok": False, "message": "اختر الشركة والفرع أولا."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = request.POST

    command = (payload.get("command") or payload.get("question") or "").strip()
    if not command:
        return JsonResponse({"ok": False, "message": "اكتب أو قل طلبك أولا."}, status=400)

    pending = request.session.get("ai_pending_command")
    result = analyze_and_route_user_request(branch_id, command, pending=pending, user=request.user)
    if result.get("pending"):
        request.session["ai_pending_command"] = result["pending"]
    else:
        request.session.pop("ai_pending_command", None)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})
