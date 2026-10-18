from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required
from apps.core.jobs import enqueue

from .forms import EpisodeForm, InterviewTextForm, StyleForm
from .models import Episode, InterviewAnswer, InterviewQuestion
from .services import get_or_create_profile

MIN_ANSWERS_FOR_EPISODES = 3


@stylist_required
def interview(request):
    questions = list(InterviewQuestion.objects.filter(is_active=True))
    answers = {a.question_id: a for a in InterviewAnswer.objects.filter(stylist=request.stylist)}
    rows = [{"question": q, "answer": answers.get(q.id)} for q in questions]
    answered = sum(1 for r in rows if r["answer"] and r["answer"].status == InterviewAnswer.Status.DONE and r["answer"].transcript)
    next_q = next((r["question"] for r in rows if not r["answer"] or not r["answer"].transcript), None)
    return render(
        request,
        "profiles/interview.html",
        {
            "rows": rows,
            "answered": answered,
            "total": len(rows),
            "can_generate": answered >= MIN_ANSWERS_FOR_EPISODES,
            "min_answers": MIN_ANSWERS_FOR_EPISODES,
            "next_question": next_q,
            "episode_count": Episode.objects.filter(stylist=request.stylist).count(),
        },
    )


@stylist_required
def interview_question(request, order: int):
    question = get_object_or_404(InterviewQuestion, order=order, is_active=True)
    answer = InterviewAnswer.objects.filter(stylist=request.stylist, question=question).first()
    next_question = InterviewQuestion.objects.filter(is_active=True, order__gt=order).order_by("order").first()
    prev_question = InterviewQuestion.objects.filter(is_active=True, order__lt=order).order_by("-order").first()

    if request.method == "POST":
        audio = request.FILES.get("audio")
        form = InterviewTextForm(request.POST)
        form.is_valid()
        transcript = (form.cleaned_data.get("transcript") or "").strip()
        if not audio and not transcript:
            if request.headers.get("X-Requested-With") == "fetch":
                return JsonResponse({"error": "音声かテキストのどちらかを入力してください"}, status=400)
            messages.error(request, "音声かテキストのどちらかを入力してください")
            return redirect("profiles:interview_question", order=order)

        answer, _ = InterviewAnswer.objects.get_or_create(stylist=request.stylist, question=question)
        if audio:
            answer.audio = audio
            answer.transcript = transcript
            answer.status = InterviewAnswer.Status.PENDING
            answer.save()
            enqueue("apps.profiles.tasks.transcribe_answer", answer.id)
        else:
            answer.transcript = transcript
            answer.status = InterviewAnswer.Status.DONE
            answer.save()

        next_url = reverse("profiles:interview_question", kwargs={"order": next_question.order}) if next_question else reverse("profiles:interview")
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse({"ok": True, "next": next_url})
        return redirect(next_url)

    form = InterviewTextForm(initial={"transcript": answer.transcript if answer else ""})
    return render(
        request,
        "profiles/interview_question.html",
        {
            "question": question,
            "answer": answer,
            "form": form,
            "next_question": next_question,
            "prev_question": prev_question,
            "total": InterviewQuestion.objects.filter(is_active=True).count(),
        },
    )


@stylist_required
@require_POST
def interview_generate(request):
    done = InterviewAnswer.objects.filter(stylist=request.stylist, status=InterviewAnswer.Status.DONE).exclude(transcript="").count()
    if done < MIN_ANSWERS_FOR_EPISODES:
        messages.error(request, f"エピソード生成には{MIN_ANSWERS_FOR_EPISODES}問以上の回答が必要です")
        return redirect("profiles:interview")
    enqueue("apps.profiles.tasks.build_episodes", request.stylist.id)
    messages.success(request, "エピソードの生成を開始しました。1〜2分ほどで一覧に追加されます。")
    return redirect("profiles:episode_list")


@stylist_required
def style_settings(request):
    profile = get_or_create_profile(request.stylist)
    form = StyleForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "文体設定を保存しました")
        return redirect("core:settings_menu")
    return render(request, "profiles/style_settings.html", {"form": form})


@stylist_required
def episode_list(request):
    episodes = Episode.objects.filter(stylist=request.stylist).prefetch_related("usages")
    return render(request, "profiles/episode_list.html", {"episodes": episodes})


@stylist_required
def episode_create(request):
    form = EpisodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ep = form.save(commit=False)
        ep.stylist = request.stylist
        ep.source = Episode.Source.MANUAL
        ep.save()
        messages.success(request, "エピソードを追加しました")
        return redirect("profiles:episode_list")
    return render(request, "profiles/episode_form.html", {"form": form, "is_new": True})


@stylist_required
def episode_edit(request, pk: int):
    episode = get_object_or_404(Episode, pk=pk, stylist=request.stylist)
    form = EpisodeForm(request.POST or None, instance=episode)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "保存しました")
        return redirect("profiles:episode_list")
    return render(request, "profiles/episode_form.html", {"form": form, "episode": episode, "is_new": False})


@stylist_required
@require_POST
def episode_delete(request, pk: int):
    episode = get_object_or_404(Episode, pk=pk, stylist=request.stylist)
    episode.delete()
    messages.success(request, "削除しました")
    return redirect("profiles:episode_list")


@stylist_required
@require_POST
def episode_toggle(request, pk: int):
    episode = get_object_or_404(Episode, pk=pk, stylist=request.stylist)
    episode.is_active = not episode.is_active
    episode.save(update_fields=["is_active", "updated_at"])
    return redirect("profiles:episode_list")
