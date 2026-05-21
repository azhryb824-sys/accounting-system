from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_employee_employeeadvance_salaryrecord'),
    ]

    operations = [
        migrations.AddField(
            model_name='salaryrecord',
            name='accrual_entry',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='salary_accrual_records', to='core.journalentry'),
        ),
        migrations.AddField(
            model_name='salaryrecord',
            name='payment_entry',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='salary_payment_records', to='core.journalentry'),
        ),
        migrations.AddField(
            model_name='employeeadvance',
            name='journal_entry',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='employee_advances', to='core.journalentry'),
        ),
    ]
