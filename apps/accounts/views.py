import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required

from .forms import AccountDeleteForm, LoginForm, SignupForm, StylistBasicForm
from .models import Stylist


def signup(request):
    if request.user.is_authenticated:
        return redirect("core:today")
    if not settings.SIGNUP_ENABLED:
        return render(request, "accounts/signup_closed.html", status=403)
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "アカウントを作成しました。最初に基本情報を設定しましょう。")
        return redirect("accounts:onboarding_basic")
    return render(request, "accounts/signup.html", {"form": form})


class StylistLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
def onboarding_basic(request):
    stylist = getattr(request.user, "stylist", None)
    if stylist is None:
        stylist = Stylist.objects.create(user=request.user, display_name=request.user.name or request.user.email.split("@")[0])
    form = StylistBasicForm(request.POST or None, instance=stylist)
    if request.method == "POST" and form.is_valid():
        form.save()
        if not stylist.onboarding_completed:
            return redirect("accounts:onboarding_line")
        messages.success(request, "基本情報を保存しました")
        return redirect("core:settings_menu")
    return render(request, "accounts/onboarding_basic.html", {"form": form, "step": 1})


@stylist_required
def onboarding_line(request):
    """LINE連携は後からでも設定できるので、ここではスキップ可能にする。"""
    from apps.lineapp.forms import LineChannelForm
    from apps.lineapp.models import LineChannel

    channel = LineChannel.objects.filter(stylist=request.stylist).first()
    form = LineChannelForm(request.POST or None, instance=channel)
    if request.method == "POST":
        if "skip" in request.POST:
            return redirect("accounts:onboarding_interview")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.stylist = request.stylist
            obj.save()
            messages.success(request, "LINEチャネル情報を保存しました。接続確認は設定画面からできます。")
            return redirect("accounts:onboarding_interview")
    return render(request, "accounts/onboarding_line.html", {"form": form, "step": 2})


@stylist_required
def onboarding_interview(request):
    if request.method == "POST":
        stylist = request.stylist
        stylist.onboarding_completed = True
        stylist.save(update_fields=["onboarding_completed", "updated_at"])
        if "start" in request.POST:
            return redirect("profiles:interview")
        messages.info(request, "インタビューは「設定 › プロフィール」からいつでも始められます。")
        return redirect("core:today")
    return render(request, "accounts/onboarding_interview.html", {"step": 3})


@stylist_required
def stylist_settings(request):
    form = StylistBasicForm(request.POST or None, instance=request.stylist)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "保存しました")
        return redirect("core:settings_menu")
    return render(request, "accounts/stylist_settings.html", {"form": form})


@stylist_required
def account_delete(request):
    form = AccountDeleteForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        logout(request)
        user.delete()  # Stylist 以下すべて CASCADE で削除（顧客データ含む）
        messages.success(request, "アカウントと関連データをすべて削除しました")
        return redirect("accounts:login")
    return render(request, "accounts/account_delete.html", {"form": form})


@stylist_required
def export_data(request):
    """個人情報保護法対応：自分（美容師）のデータをJSONで持ち出せるようにする。"""
    from apps.customers.models import Customer
    from apps.karte.models import Karte
    from apps.visits.models import Reservation, Visit

    stylist = request.stylist
    payload = {
        "stylist": {"display_name": stylist.display_name, "salon_name": stylist.salon_name, "hotpepper_url": stylist.hotpepper_url},
        "customers": list(
            Customer.objects.filter(stylist=stylist).values(
                "id", "name", "kana", "line_user_id", "contact_ok", "photo_ok", "face_ok", "story_ok", "memo", "created_at"
            )
        ),
        "kartes": list(
            Karte.objects.filter(stylist=stylist).values(
                "id", "customer_id", "visited_on", "treatment_summary", "concerns", "results", "next_check_items", "next_visit_weeks", "private_notes"
            )
        ),
        "visits": list(Visit.objects.filter(stylist=stylist).values("id", "customer_id", "visited_at", "menu", "price", "duration_minutes")),
        "reservations": list(Reservation.objects.filter(stylist=stylist).values("id", "customer_id", "reserved_for", "menu", "status", "source")),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    response = HttpResponse(body, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="tomoni-export.json"'
    return response
