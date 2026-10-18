from . import services


def generate_sns_post(post_id: int) -> None:
    services.generate_sns_post(post_id)
