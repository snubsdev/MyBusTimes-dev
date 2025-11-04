from django.utils import timezone

class UpdateLastActiveMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = request.user
        if user.is_authenticated:
            user.last_active = timezone.now()
            user.last_ip = self.get_client_ip(request)
            user.save(update_fields=['last_active', 'last_ip'])
        return response

    def get_client_ip(self, request):
        """
        Safely get the real client IP address.
        """
        # If you're behind Cloudflare:
        if "HTTP_CF_CONNECTING_IP" in request.META:
            return request.META["HTTP_CF_CONNECTING_IP"]

        # Common reverse proxy header
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # Only take the first IP (real client)
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR", "")
        return ip
