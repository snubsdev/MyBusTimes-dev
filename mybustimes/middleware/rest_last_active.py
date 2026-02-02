import ipaddress
import uuid
import hashlib
from django.utils import timezone
from django.conf import settings
from django.http import HttpResponseForbidden
from main.cloudflare_ips import get_cloudflare_networks
from django.utils.timezone import now
from django.core.cache import cache

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
        fp = fp.strip()[:64]  # Limit length to prevent abuse
        if fp:
            return fp, False
    # Then cookie
    cookie_fp = request.COOKIES.get('mbt_device_fp')
    if cookie_fp:
        cookie_fp = cookie_fp.strip()[:64]
        if cookie_fp:
            return cookie_fp, False

    # Otherwise generate a new fingerprint for the device and mark it so we can set cookie later
    new_fp = uuid.uuid4().hex
    request._generated_device_fp = new_fp
    return new_fp, True


def derive_device_fingerprint(request):
    """Create a best-effort derived fingerprint from stable request headers.

    This is a fallback used when no explicit device fingerprint cookie/header
    is present so bans can still apply across some browser changes.
    """
    parts = []
    ua = request.META.get('HTTP_USER_AGENT', '')
    if ua:
        parts.append(ua)
    al = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
    if al:
        parts.append(al)
    acc = request.META.get('HTTP_ACCEPT', '')
    if acc:
        parts.append(acc)
    sec_ua = request.META.get('HTTP_SEC_CH_UA', '')
    if sec_ua:
        parts.append(sec_ua)
    sec_mobile = request.META.get('HTTP_SEC_CH_UA_MOBILE', '')
    if sec_mobile:
        parts.append(sec_mobile)

    if not parts:
        return None

    data = "|".join(parts).encode('utf-8')
    return 'derived-' + hashlib.sha256(data).hexdigest()


def check_device_ban_cached(device_fp, derived_fp, ip_for_storage, user_agent):
    """Check device bans with aggressive caching to reduce DB queries."""
    
    # Cache ban checks for 60 seconds to avoid repeated queries
    cache_key = f'device_ban_check:{device_fp}:{derived_fp}:{ip_for_storage}'
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result
    
    banned = False
    
    try:
        # 1) Check explicit fingerprint
        if device_fp and DeviceBan.objects.filter(fingerprint=device_fp, active=True).exists():
            banned = True
        
        # 2) Check derived fingerprint
        if not banned and derived_fp and DeviceBan.objects.filter(fingerprint=derived_fp, active=True).exists():
            banned = True
        
        # 3) Check devices from same IP - with select_related and values_list for efficiency
        if not banned and ip_for_storage:
            # Get fingerprints from this IP
            fps = list(Device.objects.filter(last_ip=ip_for_storage).values_list('fingerprint', flat=True)[:100])
            
            if fps and DeviceBan.objects.filter(fingerprint__in=fps, active=True).exists():
                banned = True
            
            # Check devices with same IP + User-Agent
            if not banned and user_agent:
                ua_match = user_agent[:150]
                fps2 = list(Device.objects.filter(
                    last_ip=ip_for_storage,
                    user_agent__startswith=ua_match
                ).values_list('fingerprint', flat=True)[:100])
                
                if fps2 and DeviceBan.objects.filter(fingerprint__in=fps2, active=True).exists():
                    banned = True
    except Exception:
        pass
    
    # Cache the result for 60 seconds
    cache.set(cache_key, banned, 60)
    return banned


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
        print("[DEBUG] Initializing UpdateLastActiveMiddleware")

    def __call__(self, request):
        print("[DEBUG] Entering __call__ in UpdateLastActiveMiddleware")
        # Process the request and get the response
        response = self.get_response(request)
        
        print("[DEBUG] Response obtained in __call__")
        
        # Post-processing: set device fingerprint cookie if generated
        gen = getattr(request, '_generated_device_fp', None)
        if gen:
            # Set cookie for a long duration (10 years)
            max_age = 10 * 365 * 24 * 60 * 60
            secure_flag = getattr(settings, 'SESSION_COOKIE_SECURE', False)
            response.set_cookie('mbt_device_fp', gen, max_age=max_age, secure=secure_flag, httponly=True, samesite='Lax')
        
        print("[DEBUG] Exiting __call__ in UpdateLastActiveMiddleware")
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Pre-process before view is called. Return None to continue, or HttpResponse to short-circuit."""
        print("[DEBUG] Entering process_view in UpdateLastActiveMiddleware")
        
        # Update last_active for authenticated users - but only if >1 minute since last update
        # This reduces database writes significantly
        if request.user.is_authenticated:
            print(f"[DEBUG] User {request.user.username} is authenticated")
            
            # Only update if >60 seconds since last update to reduce DB writes
            should_update = False
            if request.user.last_active is None:
                should_update = True
            else:
                time_since_update = (timezone.now() - request.user.last_active).total_seconds()
                if time_since_update > 60:
                    should_update = True
            
            if should_update:
                request.user.last_active = now()
                request.user.save(update_fields=['last_active'])
                print(f"[DEBUG] Updated last_active for user {request.user.username}")
            else:
                print(f"[DEBUG] Skipped last_active update (recent)")

        # Attach or generate device fingerprint
        print("[DEBUG] Getting device fingerprint")
        device_fp, was_generated = get_device_fingerprint(request)
        print(f"[DEBUG] Device fingerprint: {device_fp}, Was generated: {was_generated}")
        
        # Best-effort derived fingerprint from headers (fallback)
        print("[DEBUG] Deriving device fingerprint")
        derived_fp = derive_device_fingerprint(request)
        print(f"[DEBUG] Derived fingerprint: {derived_fp}")
        
        request.device_fingerprint = device_fp
        request.derived_device_fp = derived_fp

        # Determine a storable client IP (ignore Cloudflare edge IPs)
        print("[DEBUG] Determining client IP")
        ip_for_storage = get_real_ip(request)
        if not ip_for_storage or is_cloudflare_ip(ip_for_storage):
            ip_for_storage = None
        print(f"[DEBUG] Client IP for storage: {ip_for_storage}")

        # Check for device bans (skip for admin pages)
        if not request.path.startswith('/api-admin/') and not request.path.startswith('/admin/'):
            print("[DEBUG] Checking for device bans")
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Use cached ban check to avoid repeated queries
            if check_device_ban_cached(device_fp, derived_fp, ip_for_storage, user_agent):
                return HttpResponseForbidden('Device banned')

        # Record device usage with bulk operations and caching
        print("[DEBUG] Recording device usage")
        try:
            chosen_fp = None
            # Only use explicit fingerprint if it came from header/cookie, not generated
            if device_fp and not was_generated:
                chosen_fp = device_fp
            elif derived_fp:
                chosen_fp = derived_fp
            else:
                chosen_fp = device_fp  # Use generated fingerprint

            if chosen_fp:
                print(f"[DEBUG] Recording usage for fingerprint: {chosen_fp}")
                
                # Use get_or_create with defaults to reduce queries
                dev, created = Device.objects.get_or_create(
                    fingerprint=chosen_fp,
                    defaults={
                        'last_ip': ip_for_storage,
                        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:1000],
                        'last_user': request.user if request.user.is_authenticated else None,
                        'seen_count': 1
                    }
                )
                
                # Only update if not just created
                if not created:
                    # Batch updates - only update fields that changed
                    update_fields = []
                    
                    dev.last_seen = timezone.now()
                    update_fields.append('last_seen')
                    
                    if ip_for_storage and dev.last_ip != ip_for_storage:
                        dev.last_ip = ip_for_storage
                        update_fields.append('last_ip')
                    
                    ua = request.META.get('HTTP_USER_AGENT')
                    if ua and dev.user_agent != ua[:1000]:
                        dev.user_agent = ua[:1000]
                        update_fields.append('user_agent')
                    
                    if request.user.is_authenticated and dev.last_user != request.user:
                        dev.last_user = request.user
                        update_fields.append('last_user')
                    
                    dev.seen_count = (dev.seen_count or 0) + 1
                    update_fields.append('seen_count')
                    
                    if update_fields:
                        dev.save(update_fields=update_fields)

                # Record user-device association
                if request.user.is_authenticated:
                    du, du_created = DeviceUsage.objects.get_or_create(
                        device=dev,
                        user=request.user,
                        defaults={'usage_count': 1}
                    )
                    if not du_created:
                        du.last_seen = timezone.now()
                        du.usage_count = du.usage_count + 1
                        du.save(update_fields=['last_seen', 'usage_count'])
        except Exception as e:
            print(f"[DEBUG] Error recording device usage: {e}")

        # Update user's last IP only if it changed
        user = request.user
        if user.is_authenticated:
            print(f"[DEBUG] Updating user's last IP")
            new_ip = get_real_ip(request)

            # Do not save Cloudflare edge IPs
            if not new_ip or is_cloudflare_ip(new_ip):
                new_ip = user.last_ip  # keep previous valid IP

            # Only update DB if IP actually changed
            if user.last_ip != new_ip:
                print(f"[DEBUG] Updating last_ip for user {user.username}")
                user.last_ip = new_ip
                user.save(update_fields=["last_ip"])

        print("[DEBUG] Exiting process_view in UpdateLastActiveMiddleware")
        # Return None to allow normal view processing
        return None