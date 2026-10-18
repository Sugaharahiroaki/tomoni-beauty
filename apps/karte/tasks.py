from . import services


def process_voice_memo(memo_id: int) -> None:
    services.process_voice_memo(memo_id)
