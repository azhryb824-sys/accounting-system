from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import PurchaseItem


@receiver(post_save, sender=PurchaseItem)
def update_inventory(sender, instance, created, **kwargs):
    if created:
        item = instance.item
        item.quantity += instance.quantity
        item.cost = instance.price
        item.save()
