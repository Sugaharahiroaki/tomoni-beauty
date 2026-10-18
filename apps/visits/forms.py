from django import forms

from apps.customers.models import Customer

from .models import Reservation, Visit

DATETIME_LOCAL_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"]


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%dT%H:%M")
        super().__init__(**kwargs)


class ReservationForm(forms.ModelForm):
    reserved_for = forms.DateTimeField(label="予約日時", widget=DateTimeLocalInput(), input_formats=DATETIME_LOCAL_FORMATS)

    class Meta:
        model = Reservation
        fields = ["customer", "customer_name_raw", "reserved_for", "menu", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, stylist=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(stylist=stylist).order_by("name")
        self.fields["customer"].required = False
        self.fields["customer"].empty_label = "（未登録のお客様）"
        self.fields["customer_name_raw"].label = "お名前（未登録の場合）"

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("customer") and not cleaned.get("customer_name_raw"):
            raise forms.ValidationError("お客様を選ぶか、お名前を入力してください")
        return cleaned


class VisitForm(forms.ModelForm):
    visited_at = forms.DateTimeField(label="来店日時", widget=DateTimeLocalInput(), input_formats=DATETIME_LOCAL_FORMATS)

    class Meta:
        model = Visit
        fields = ["customer", "visited_at", "menu", "price", "duration_minutes"]
        widgets = {"price": forms.NumberInput(attrs={"inputmode": "numeric"}), "duration_minutes": forms.NumberInput(attrs={"inputmode": "numeric"})}

    def __init__(self, *args, stylist=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(stylist=stylist).order_by("name")
