APP_LABELS = {
    "accounts": "المستخدمون والاشتراكات",
    "core": "الحسابات والشركات",
    "invoicing": "الفواتير والمخزون",
}

MODEL_LABELS = {
    "account": "دليل الحسابات",
    "branch": "الفروع",
    "company": "الشركات",
    "companyjoinrequest": "طلبات الانضمام للشركات",
    "companymembership": "عضويات الشركات",
    "customer": "العملاء",
    "employee": "الموظفون",
    "employeeadvance": "سلف الموظفين",
    "fingerprintcredential": "بصمة الدخول",
    "invoice": "فواتير البيع",
    "invoiceitem": "بنود فواتير البيع",
    "item": "المنتجات والأصناف",
    "journalentry": "القيود اليومية",
    "journalentryline": "بنود القيود",
    "monthlyclose": "القفل الشهري",
    "purchaseinvoice": "فواتير الشراء والذكاء الاصطناعي",
    "purchaseitem": "بنود فواتير الشراء",
    "role": "الأدوار",
    "salaryrecord": "رواتب الموظفين",
    "stockmovement": "حركة المخزون",
    "subscriptionplan": "باقات الاشتراك",
    "subscriptionrequest": "طلبات الاشتراك",
    "supplier": "الموردون",
    "tax": "الضرائب",
    "userprofile": "ملفات المستخدمين",
    "userwarning": "تنبيهات المستخدمين",
}

ACTION_LABELS = {
    "add": "إضافة",
    "view": "عرض",
    "change": "تعديل",
    "delete": "حذف",
    "close": "قفل",
    "reopen": "فتح",
    "import": "استيراد",
}

CODENAME_LABELS = {
    "import_ai_invoice": "إضافة فاتورة بالذكاء الاصطناعي",
    "view_ai_insights": "نصائح وتوقعات الذكاء الاصطناعي",
    "close_month": "قفل شهر",
    "reopen_month": "إعادة فتح شهر",
}


def app_label(content_type):
    return APP_LABELS.get(content_type.app_label, content_type.app_label)


def model_label(content_type):
    return MODEL_LABELS.get(content_type.model, content_type.name)


def action_label(permission):
    if permission.codename in CODENAME_LABELS:
        return CODENAME_LABELS[permission.codename]
    action = permission.codename.split("_", 1)[0]
    return ACTION_LABELS.get(action, permission.name)
