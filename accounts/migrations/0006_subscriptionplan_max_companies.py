from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_require_trial_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionplan',
            name='max_companies',
            field=models.PositiveIntegerField(default=1),
        ),
    ]
