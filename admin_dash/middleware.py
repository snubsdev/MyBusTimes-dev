from django.shortcuts import redirect
from django.conf import settings


class RequireOTPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/') or request.path.startswith('/api-admin/'):
            if not request.user.is_authenticated:
                return redirect(settings.LOGIN_URL)
            if not request.user.is_verified():
                return redirect('/account/two_factor/setup/')
        return self.get_response(request)