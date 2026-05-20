from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_subscriptionplan_permissions'),
        ('core', '0002_company_owner_company_owner_role_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='active_plan',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='active_companies', to='accounts.subscriptionplan'),
        ),
        migrations.AddField(
            model_name='company',
            name='subscription_ends_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='company',
            name='subscription_starts_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='company',
            name='trial_ends_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
