# إنشاء حساب المشرف بعد تنزيل المشروع

لا يتم رفع قاعدة البيانات `db.sqlite3` إلى GitHub لأنها تحتوي بيانات مستخدمين وجلسات ومعلومات حساسة.

بعد تنزيل المشروع وتشغيل الهجرات:

```powershell
python manage.py migrate
python manage.py bootstrap_admin --username admin --password "Admin@12345" --email "admin@example.com" --national-id 2572280689
```

بعدها سجّل الدخول برقم الهوية:

```text
2572280689
```

وكلمة المرور التي وضعتها في الأمر.

يفضل تغيير كلمة المرور بعد أول دخول.
