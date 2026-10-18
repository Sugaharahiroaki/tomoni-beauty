"""データを消したら、サーバーに置いてあるファイル（写真・動画・録音）も消す。"""

from django.db.models import FileField
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import BgmTrack, MediaAsset, NarrationTake, ReelPost, ShotExample


def delete_files(instance):
    for field in instance._meta.get_fields():
        if isinstance(field, FileField):
            f = getattr(instance, field.name)
            if f and f.name:
                try:
                    f.storage.delete(f.name)
                except Exception:  # noqa: BLE001
                    pass


@receiver(post_delete, sender=MediaAsset)
def media_asset_deleted(sender, instance, **kwargs):
    delete_files(instance)
    poster = (instance.analysis or {}).get("poster_name")
    if poster:
        try:
            instance.file.storage.delete(poster)
        except Exception:  # noqa: BLE001
            pass


@receiver(post_delete, sender=ReelPost)
@receiver(post_delete, sender=NarrationTake)
@receiver(post_delete, sender=BgmTrack)
@receiver(post_delete, sender=ShotExample)
def files_deleted(sender, instance, **kwargs):
    delete_files(instance)
