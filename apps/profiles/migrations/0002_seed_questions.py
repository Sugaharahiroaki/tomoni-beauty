from django.db import migrations


def seed_questions(apps, schema_editor):
    from apps.profiles.questions import INTERVIEW_QUESTIONS

    InterviewQuestion = apps.get_model("profiles", "InterviewQuestion")
    for order, text, hint, theme in INTERVIEW_QUESTIONS:
        InterviewQuestion.objects.update_or_create(order=order, defaults={"text": text, "hint": hint, "theme": theme, "is_active": True})


def unseed(apps, schema_editor):
    InterviewQuestion = apps.get_model("profiles", "InterviewQuestion")
    InterviewQuestion.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("profiles", "0001_initial")]
    operations = [migrations.RunPython(seed_questions, unseed)]
