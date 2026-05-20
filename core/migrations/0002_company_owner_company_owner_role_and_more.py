from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_subscriptionplan_display_order_and_more'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_companies', to='auth.user'),
        ),
        migrations.AddField(
            model_name='company',
            name='owner_role',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_companies', to='accounts.role'),
        ),
        migrations.AddField(
            model_name='company',
            name='subscription_status',
            field=models.CharField(choices=[('pending', 'بانتظار الموافقة'), ('active', 'نشطة'), ('rejected', 'مرفوضة')], default='pending', max_length=20),
        ),
    ]
