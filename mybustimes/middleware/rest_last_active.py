import logging
import ipaddress
import uuid
import hashlib
import random
import time
import tracemalloc
from django.utils import timezone
from django.db.models import F
from django.conf import settings
from django.http import HttpResponseForbidden
from main.cloudflare_ips import get_cloudflare_networks
from django.utils.timezone import now
from django.core.cache import cache

# Import DeviceBan model for banning by device fingerprint
from main.models import DeviceBan, Device, DeviceUsage

try:
    import psutil
except ImportError:  # pragma: no cover - handled gracefully if dependency is missing
    psutil = None


memory_logger = logging.getLogger('memory_diagnostics')
DEFAULT_MEMORY_IGNORED_PATH_PREFIXES = ('/static/', '/media/', '/favicon.ico', '/robots.txt')


def _bytes_to_mb(value):
    if value is None:
        return None
    return value / (1024 * 1024)


def _format_mb(value):
    if value is None:
        return 'n/a'
    return f'{_bytes_to_mb(value):.1f}MB'


def _get_rss_bytes(process):
    if process is None:
        return None

    try:
        return process.memory_info().rss
    except Exception:
        return None


def _should_profile_request(request):
    if not getattr(settings, 'MEMORY_DIAGNOSTICS_ENABLED', False):
        return False

    ignored_prefixes = tuple(
        getattr(settings, 'MEMORY_DIAGNOSTICS_IGNORED_PATH_PREFIXES', DEFAULT_MEMORY_IGNORED_PATH_PREFIXES)
    )
    if ignored_prefixes and request.path.startswith(ignored_prefixes):
        return False

    sample_rate = getattr(settings, 'MEMORY_DIAGNOSTICS_SAMPLE_RATE', 1.0)
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True

    return random.random() <= sample_rate


def _log_top_allocations():
    if not tracemalloc.is_tracing():
        return

    limit = max(getattr(settings, 'MEMORY_DIAGNOSTICS_TRACE_LIMIT', 8), 1)

    try:
        snapshot = tracemalloc.take_snapshot()
        for index, stat in enumerate(snapshot.statistics('lineno')[:limit], start=1):
            memory_logger.warning('[MEM] top_alloc_%s %s', index, stat)
    except Exception as exc:
        memory_logger.warning('[MEM] failed_to_capture_tracemalloc_snapshot error=%s', exc)


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
        if not banned and ip_for_storage and ip_for_storage not in ('127.0.0.1', '::1'):
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
        self._memory_process = psutil.Process() if psutil and getattr(settings, 'MEMORY_DIAGNOSTICS_ENABLED', False) else None

        if getattr(settings, 'MEMORY_DIAGNOSTICS_ENABLED', False):
            if psutil is None:
                memory_logger.warning('[MEM] diagnostics_enabled_without_psutil rss_logging_disabled=true')

            trace_frames = max(getattr(settings, 'MEMORY_DIAGNOSTICS_TRACE_FRAMES', 25), 1)
            if not tracemalloc.is_tracing():
                tracemalloc.start(trace_frames)

    def __call__(self, request):
        memory_profile = None
        if _should_profile_request(request):
            memory_profile = {
                'started_at': time.perf_counter(),
                'rss_before': _get_rss_bytes(self._memory_process),
            }

        # Process the request and get the response
        try:
            response = self.get_response(request)
        except Exception as exc:
            self._log_memory_profile(request, response=None, profile=memory_profile, exception=exc)
            raise

        self._log_memory_profile(request, response=response, profile=memory_profile)
        
        # Post-processing: set device fingerprint cookie if generated
        gen = getattr(request, '_generated_device_fp', None)
        if gen:
            # Set cookie for a long duration (10 years)
            max_age = 10 * 365 * 24 * 60 * 60
            secure_flag = getattr(settings, 'SESSION_COOKIE_SECURE', False)
            response.set_cookie('mbt_device_fp', gen, max_age=max_age, secure=secure_flag, httponly=True, samesite='Lax')

        # Post-processing: record device usage and update user IP after response
        try:
            device_fp = getattr(request, '_device_fp', None)
            derived_fp = getattr(request, '_derived_fp', None)
            was_generated = getattr(request, '_device_fp_generated', False)
            ip_for_storage = getattr(request, '_ip_for_storage', None)
            user_agent = getattr(request, '_user_agent', '')

            chosen_fp = None
            if device_fp and not was_generated:
                chosen_fp = device_fp
            elif derived_fp:
                chosen_fp = derived_fp
            else:
                chosen_fp = device_fp

            if chosen_fp:
                dev, created = Device.objects.get_or_create(
                    fingerprint=chosen_fp,
                    defaults={
                        'last_ip': ip_for_storage,
                        'user_agent': user_agent[:1000],
                        'last_user': request.user if request.user.is_authenticated else None,
                        'seen_count': 1
                    }
                )

                if not created:
                    update_fields = []

                    dev.last_seen = timezone.now()
                    update_fields.append('last_seen')

                    if ip_for_storage and dev.last_ip != ip_for_storage:
                        dev.last_ip = ip_for_storage
                        update_fields.append('last_ip')

                    if user_agent and dev.user_agent != user_agent[:1000]:
                        dev.user_agent = user_agent[:1000]
                        update_fields.append('user_agent')

                    if request.user.is_authenticated and dev.last_user != request.user:
                        dev.last_user = request.user
                        update_fields.append('last_user')

                    if update_fields:
                        dev.save(update_fields=update_fields)

                    Device.objects.filter(pk=dev.pk).update(
                        seen_count=F('seen_count') + 1
                    )

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

            user = request.user
            if user.is_authenticated:
                new_ip = get_real_ip(request)

                if not new_ip or is_cloudflare_ip(new_ip):
                    new_ip = user.last_ip

                if user.last_ip != new_ip:
                    user.last_ip = new_ip
                    user.save(update_fields=["last_ip"])
        except Exception as e:
            #print(f"[DEBUG] Error recording device usage: {e}")
            pass
        
        return response

    def _log_memory_profile(self, request, response, profile, exception=None):
        if not profile:
            return

        rss_after = _get_rss_bytes(self._memory_process)
        rss_before = profile.get('rss_before')
        rss_delta = None if rss_before is None or rss_after is None else rss_after - rss_before
        duration_ms = (time.perf_counter() - profile['started_at']) * 1000

        threshold_bytes = int(getattr(settings, 'MEMORY_DIAGNOSTICS_THRESHOLD_MB', 500) * 1024 * 1024)
        delta_threshold_bytes = int(getattr(settings, 'MEMORY_DIAGNOSTICS_DELTA_MB', 100) * 1024 * 1024)

        over_absolute_threshold = rss_after is not None and rss_after >= threshold_bytes
        over_delta_threshold = rss_delta is not None and rss_delta >= delta_threshold_bytes

        status_code = getattr(response, 'status_code', 500)
        view_name = getattr(request, '_memory_view_name', None)
        if not view_name:
            resolver_match = getattr(request, 'resolver_match', None)
            view_name = getattr(resolver_match, 'view_name', None) or 'unknown'

        level = logging.INFO
        if exception is not None:
            level = logging.ERROR
        elif over_absolute_threshold or over_delta_threshold:
            level = logging.WARNING

        memory_logger.log(
            level,
            '[MEM] method=%s path=%s view=%s status=%s duration_ms=%.1f rss_before=%s rss_after=%s rss_delta=%s exception=%s',
            request.method,
            request.path,
            view_name,
            status_code,
            duration_ms,
            _format_mb(rss_before),
            _format_mb(rss_after),
            _format_mb(rss_delta),
            exception.__class__.__name__ if exception else 'none',
        )

        if over_absolute_threshold or over_delta_threshold or exception is not None:
            _log_top_allocations()

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Pre-process before view is called. Return None to continue, or HttpResponse to short-circuit."""
        request._memory_view_name = f'{view_func.__module__}.{getattr(view_func, "__name__", view_func.__class__.__name__)}'
        
        # Update last_active for authenticated users - but only if >1 minute since last update
        # This reduces database writes significantly
        if request.user.is_authenticated:
            
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
            else:
                pass  # Skip update to reduce DB writes
            
        device_fp, was_generated = get_device_fingerprint(request)

        derived_fp = derive_device_fingerprint(request)
        
        request.device_fingerprint = device_fp
        request.derived_device_fp = derived_fp
        request._device_fp = device_fp
        request._derived_fp = derived_fp
        request._device_fp_generated = was_generated

        ip_for_storage = get_real_ip(request)
        if not ip_for_storage or is_cloudflare_ip(ip_for_storage):
            ip_for_storage = None
        request._ip_for_storage = ip_for_storage
        request._user_agent = request.META.get('HTTP_USER_AGENT', '')

        # Check for device bans (skip for admin pages)
        if not request.path.startswith('/api-admin/') and not request.path.startswith('/admin/'):
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Use cached ban check to avoid repeated queries
            if check_device_ban_cached(device_fp, derived_fp, ip_for_storage, user_agent):
                request.device_ban_checked = True
                request.device_banned = True
                return HttpResponseForbidden('Device banned')
            request.device_ban_checked = True
            request.device_banned = False
        else:
            request.device_ban_checked = False
            request.device_banned = False
        # Return None to allow normal view processing
        return None