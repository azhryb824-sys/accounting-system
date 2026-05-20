from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_subscriptionrequest_company_and_more'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionplan',
            name='permissions',
            field=models.ManyToManyField(blank=True, related_name='subscription_plans', to='auth.permission'),
        ),
    ]
