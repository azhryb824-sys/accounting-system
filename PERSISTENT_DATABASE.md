# قاعدة البيانات الدائمة

حتى لا تضيع البيانات بعد كل تعديل أو نشر، يجب تشغيل الموقع على قاعدة PostgreSQL دائمة وليس SQLite داخل ملفات Render.

## Render

1. أنشئ PostgreSQL Database من لوحة Render.
2. افتح قاعدة البيانات وانسخ `Internal Database URL`.
3. افتح Web Service الخاص بالنظام.
4. من `Environment` أضف متغيرا باسم:
   `DATABASE_URL`
5. ضع فيه رابط قاعدة PostgreSQL الداخلي.
6. اجعل أمر البناء:
   `pip install -r requirements.txt && python manage.py migrate`
7. أعد النشر.

بعد ذلك لن يتم حذف بيانات الشركات والفواتير والقيود عند رفع تعديل جديد.

## التشغيل المحلي

إذا لم يوجد `DATABASE_URL` سيستمر النظام محليا باستخدام SQLite:

- `db.sqlite3` إذا كان موجودا.
- وإلا يستخدم `starter.sqlite3`.

