class StylistMiddleware:
    """ログインユーザーに紐づく美容師（テナント）を request.stylist に載せる。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.stylist = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.stylist = getattr(user, "stylist", None)
        return self.get_response(request)
