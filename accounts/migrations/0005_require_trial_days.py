from django.db import migrations, models


def enable_trial_days(apps, schema_editor):
    SubscriptionPlan = apps.get_model('accounts', 'SubscriptionPlan')
    SubscriptionPlan.objects.filter(trial_days=0).update(trial_days=7)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_subscriptionplan_permissions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subscriptionplan',
            name='trial_days',
            field=models.PositiveIntegerField(default=7),
        ),
        migrations.RunPython(enable_trial_days, migrations.RunPython.noop),
    ]
