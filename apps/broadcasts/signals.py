"""予約が増減したら、その美容師の空き枠（自動）を作り直す。"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.visits.models import Reservation

from .auto_slots import sync_auto_slots
from .models import AvailabilitySlot


@receiver(post_save, sender=Reservation)
def _reservation_saved(sender, instance, **kwargs):
    sync_auto_slots(instance.stylist)


@receiver(post_delete, sender=Reservation)
def _reservation_deleted(sender, instance, **kwargs):
    sync_auto_slots(instance.stylist)


@receiver(post_save, sender=AvailabilitySlot)
@receiver(post_delete, sender=AvailabilitySlot)
def _manual_slot_changed(sender, instance, **kwargs):
    """手で足した枠が変わったら、自動の枠を作り直す（自動の枠自身の保存では何もしない）"""
    if not instance.auto:
        sync_auto_slots(instance.stylist)
