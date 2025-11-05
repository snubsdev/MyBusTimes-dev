import ipaddress
from django.utils import timezone
from main.cloudflare_ips import get_cloudflare_networks


def is_cloudflare_ip(ip):
    ipv4_nets, ipv6_nets = get_cloudflare_networks()

    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False  # Invalid or empty IP → treat as not Cloudflare

    if ip_obj.version == 4:
        return any(ip_obj in net for net in ipv4_nets)
    else:
        return any(ip_obj in net for net in ipv6_nets)


def get_real_ip(request):
    ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if ip:
        return ip.strip()

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "").strip()


class UpdateLastActiveMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        user = request.user
        if user.is_authenticated:
            new_ip = get_real_ip(request)

            # ✅ Do not save Cloudflare edge IPs
            if not new_ip or is_cloudflare_ip(new_ip):
                new_ip = user.last_ip  # keep previous valid IP

            # ✅ Only update DB if something actually changed
            if user.last_ip != new_ip:
                user.last_ip = new_ip
                user.last_active = timezone.now()
                user.save(update_fields=["last_ip", "last_active"])
            else:
                # Only update last_active if more than 1 min passed
                # (avoid DB write spam on every request)
                if user.last_active is None or (timezone.now() - user.last_active).seconds > 60:
                    user.last_active = timezone.now()
                    user.save(update_fields=["last_active"])

        return response
