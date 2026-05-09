from django.shortcuts import redirect
from django.conf import settings
from django.utils import timezone
import datetime

class RequireOTPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/') or request.path.startswith('/api-admin/'):
            if not request.user.is_authenticated:
                return redirect(settings.LOGIN_URL)

            if not request.user.is_verified():
                return redirect('/account/two_factor/setup/')

            # Check if 2FA was recently re-verified for admin access
            last_verified = request.session.get('otp_admin_verified_at')
            OTP_REVERIFY_SECONDS = getattr(settings, 'OTP_ADMIN_REVERIFY_SECONDS', 0)

            needs_reverify = True
            if last_verified and OTP_REVERIFY_SECONDS > 0:
                elapsed = timezone.now().timestamp() - last_verified
                if elapsed < OTP_REVERIFY_SECONDS:
                    needs_reverify = False

            if needs_reverify:
                # Clear any previous re-verify session flag
                request.session.pop('otp_admin_verified_at', None)

                # Store the intended destination so we can redirect back after
                request.session['otp_admin_next'] = request.get_full_path()
                return redirect('/account/two_factor/reverify/')

        return self.get_response(request)