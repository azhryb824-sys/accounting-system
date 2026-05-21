from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_accounting_links'),
        ('invoicing', '0004_alter_purchaseinvoice_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='journal_entry',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sales_invoices', to='core.journalentry'),
        ),
        migrations.AddField(
            model_name='purchaseinvoice',
            name='journal_entry',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='purchase_invoices', to='core.journalentry'),
        ),
    ]
