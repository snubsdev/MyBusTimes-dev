import ipaddress
import uuid
from django.utils import timezone
from django.conf import settings
from django.http import HttpResponseForbidden
from main.cloudflare_ips import get_cloudflare_networks

# Import DeviceBan model for banning by device fingerprint
from main.models import DeviceBan, Device, DeviceUsage


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


def get_device_fingerprint(request):
    # Prefer explicit header (X-Device-Fingerprint)
    fp = request.META.get('HTTP_X_DEVICE_FINGERPRINT')
    if fp:
        return fp.strip(), False

    # Then cookie
    cookie_fp = request.COOKIES.get('mbt_device_fp')
    if cookie_fp:
        return cookie_fp, False

    # Otherwise generate a new fingerprint for the device and mark it so we can set cookie later
    new_fp = uuid.uuid4().hex
    request._generated_device_fp = new_fp
    return new_fp, True

class ResetProMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and user.sub_plan and user.ad_free_until and user.ad_free_until < timezone.now():
            user.sub_plan = 'free'
            user.ad_free_until = None
            user.save(update_fields=["sub_plan", "ad_free_until"])

        response = self.get_response(request)

        return response

class UpdateLastActiveMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Attach or generate device fingerprint and check bans before handling request
        device_fp, _created = get_device_fingerprint(request)
        request.device_fingerprint = device_fp

        # Determine a storable client IP (ignore Cloudflare edge IPs)
        ip_for_storage = get_real_ip(request)
        if not ip_for_storage or is_cloudflare_ip(ip_for_storage):
            ip_for_storage = None

        # If this fingerprint is banned and active, block the request immediately
        # BUT allow access to the API admin to avoid locking out admins
        if not request.path.startswith('/api-admin/'):
            if device_fp and DeviceBan.objects.filter(fingerprint=device_fp, active=True).exists():
                return HttpResponseForbidden('Device banned')

        response = self.get_response(request)

        # If we generated a fingerprint in this request, set it as a cookie on the response
        gen = getattr(request, '_generated_device_fp', None)
        if gen:
            # Set cookie for a long duration (10 years)
            max_age = 10 * 365 * 24 * 60 * 60
            secure_flag = getattr(settings, 'SESSION_COOKIE_SECURE', False)
            response.set_cookie('mbt_device_fp', gen, max_age=max_age, secure=secure_flag, httponly=True, samesite='Lax')

        # Record device usage (non-blocking)
        try:
            if device_fp:
                dev, _ = Device.objects.get_or_create(fingerprint=device_fp)
                dev.last_seen = timezone.now()
                if ip_for_storage:
                    dev.last_ip = ip_for_storage
                ua = request.META.get('HTTP_USER_AGENT')
                if ua:
                    dev.user_agent = ua[:1000]
                if request.user.is_authenticated:
                    dev.last_user = request.user
                dev.seen_count = (dev.seen_count or 0) + 1
                dev.save()

                if request.user.is_authenticated:
                    du, _ = DeviceUsage.objects.get_or_create(device=dev, user=request.user)
                    du.last_seen = timezone.now()
                    du.usage_count = du.usage_count + 1
                    du.save()
        except Exception:
            pass

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
