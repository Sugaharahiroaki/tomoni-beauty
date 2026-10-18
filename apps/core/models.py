from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    """美容師（テナント）ごとにデータを分離するための共通クエリセット。"""

    def for_stylist(self, stylist):
        return self.filter(stylist=stylist)


TenantManager = TenantQuerySet.as_manager
