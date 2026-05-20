from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_subscriptionplan_display_order_and_more'),
        ('core', '0002_company_owner_company_owner_role_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionrequest',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='subscription_requests', to='core.company'),
        ),
        migrations.AddField(
            model_name='subscriptionrequest',
            name='requested_role',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='subscription_requests', to='accounts.role'),
        ),
    ]
