# Standard library imports
import datetime
import json
import logging
import os
from datetime import timedelta
from random import randint
import re 

# Django imports
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth import logout
from rest_framework.decorators import api_view

# Third-party imports
import stripe
from dotenv import load_dotenv
from rest_framework import generics, permissions, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from dateutil.relativedelta import relativedelta 

# Local imports
from .forms import CustomUserCreationForm, AccountSettingsForm
from fleet.models import group, MBTOperator, fleetChange, helper, liverie
from main.models import CustomUser, UserKeys, badge, StripeSubscription
from a.models import AffiliateLink, Link
from group.models import Group

import requests

logger = logging.getLogger(__name__)
User = get_user_model()
stripe.api_key = settings.STRIPE_SECRET_KEY

debug = settings.DEBUG

@login_required
def link_discord_account(request):
    discord_username = request.GET.get('username', '').strip()
    if discord_username:
        user = request.user
        user.discord_username = discord_username
        user.save()

        counter = Link.objects.filter(pk=16).first()
        counter.clicks += 1
        counter.save()

        return render(request, 'link_discord.html', {'error': 'success'})

    return render(request, 'link_discord.html')

from datetime import datetime
def send_to_discord_embed(channel_id, title, message, colour=0x00BFFF):
    embed = {
        "title": title,
        "description": message,
        "color": colour,
        "fields": [
            {
                "name": "Time",
                "value": datetime.now().strftime('%Y-%m-%d %H:%M'),
                "inline": True
            }
        ],
        "footer": {
            "text": "MBT Logging System"
        },
        "timestamp": datetime.now().isoformat()
    }

    data = {
        'channel_id': channel_id,
        'embed': embed
    }

    response = requests.post(
        f"{settings.DISCORD_BOT_API_URL}/send-embed",
        json=data
    )
    response.raise_for_status()


def validate_turnstile(token, remoteip=None):
    if debug:
        return {'success': True}
    else:
        url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'

        data = {
            'secret': settings.CF_SECRET_KEY,
            'response': token
        }

        if remoteip:
            data['remoteip'] = remoteip

        try:
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Turnstile validation error: {e}")
            return {'success': False, 'error-codes': ['internal-error']}

class CustomLoginView(LoginView):
    def form_valid(self, form):
        token = self.request.POST.get('cf-turnstile-response')
        remoteip = (
            self.request.headers.get('CF-Connecting-IP')
            or self.request.headers.get('X-Forwarded-For')
            or self.request.META.get('REMOTE_ADDR')
        )

        validation = validate_turnstile(token, remoteip)

        if not validation.get('success'):
            form.add_error(None, "Captcha validation failed. Please try again.")
            return self.form_invalid(form)

        response = super().form_valid(form)
        user = self.request.user

        # Get IP address
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0] if x_forwarded_for else self.request.META.get('REMOTE_ADDR')

        # Save login info
        user.last_login_ip = ip
        user.last_login = now()
        user.save(update_fields=["last_login_ip", "last_login"])

        return response
    
def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            token = request.POST.get('cf-turnstile-response')
            remoteip = (
                request.headers.get('CF-Connecting-IP')
                or request.headers.get('X-Forwarded-For')
                or request.META.get('REMOTE_ADDR')
            )

            validation = validate_turnstile(token, remoteip)

            if validation['success']:
                if ' ' in form.cleaned_data['username']:
                    form.add_error('username', 'Username cannot contain spaces')
                else:
                    user = form.save()

                    # ✅ check for invite cookie
                    invite_id = request.COOKIES.get("invite_id")
                    if invite_id:
                        try:
                            link = AffiliateLink.objects.get(id=invite_id)
                            link.signups_from_clicks += 1
                            link.save()

                        except AffiliateLink.DoesNotExist:
                            pass

                    # log the new user in
                    user.backend = settings.AUTHENTICATION_BACKENDS[0]
                    login(request, user)

                    response = redirect(f'/u/{user.username}')

                    # ✅ optionally clear the cookie so it’s not reused
                    response.delete_cookie("invite_id")

                    return response
    else:
        form = CustomUserCreationForm()

    return render(request, 'register.html', {'form': form})

def user_profile(request, username):
    breadcrumbs = [
        {'name': 'Home', 'url': '/'},
    ]

    profile_user = get_object_or_404(CustomUser, username=username)

    # Operators owned by this user
    operators = MBTOperator.objects.filter(owner=profile_user).order_by('operator_slug')

    groups = Group.objects.filter(group_owner=profile_user).order_by('group_name')
    # Operators the user helps with
    helper_operator_links = helper.objects.filter(helper=profile_user).order_by('operator__operator_name')
    helper_operators_list = MBTOperator.objects.filter(id__in=helper_operator_links.values('operator')).order_by('operator_name')

    user_edits = fleetChange.objects.filter(user=profile_user).order_by('-create_at')[:10]

    # Check if viewing own profile
    owner = request.user == profile_user
    now = timezone.now();

    online = False
    if profile_user.last_active and profile_user.last_active > timezone.now() - timedelta(minutes=5):
        online = True

    context = {
        'breadcrumbs': breadcrumbs,
        'profile_user': profile_user,
        'operators': operators,
        'groups': groups, 
        'helper_operators_list': helper_operators_list,
        'owner': owner,
        'online': online,
        'user_edits': user_edits,
        'now': now,
    }

    return render(request, 'profile.html', context)

# Price IDs from .env
if debug == False:
    price_ids = {
        'monthly': os.getenv("PRICE_ID_MONTHLY"),
        'yearly': os.getenv("PRICE_ID_YEARLY"),
        'custom': os.getenv("PRICE_ID_CUSTOM"),
    }
else:
    price_ids = {
        'monthly': os.getenv("PRICE_ID_MONTHLY_TEST"),
        'yearly': os.getenv("PRICE_ID_YEARLY_TEST"),
        'custom': os.getenv("PRICE_ID_CUSTOM_TEST"),
    }

@login_required
def cancel_subscription(request):
    user = request.user
    subscription_id = getattr(user, 'stripe_subscription_id', None)

    if not subscription_id:
        return render(request, 'cancel_subscription.html', {
            'error_message': 'You do not have an active subscription to cancel.'
        })

    if request.method == 'POST':
        try:
            # Cancel subscription at period end (change `at_period_end=False` to cancel immediately)
            stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
            message = 'Your subscription will be cancelled at the end of the current billing period.'
            return render(request, 'cancel_subscription.html', {'success_message': message})
        except Exception as e:
            return render(request, 'cancel_subscription.html', {
                'error_message': f'Error cancelling subscription: {str(e)}'
            })

    return render(request, 'cancel_subscription.html')

@login_required
def subscribe_ad_free(request):
    today = timezone.now()
    current_sub_count = CustomUser.objects.filter(
        ad_free_until__gt=today,
        is_staff=False
    ).count()

    return render(request, 'subscribe.html', {'month_options': range(1, 13), 'current_sub_count': current_sub_count})

@login_required
def payment_success(request):
    return render(request, 'payment_success.html')

@login_required
def payment_cancel(request):
    return render(request, 'payment_cancel.html')

import datetime


class stripe_webhook(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    SUPPORTED_EVENTS = [
        "checkout.session.completed",
        "invoice.payment_succeeded",
    ]

    def handle_checkout_session_completed(self, event_data_obj):
        print("Handling checkout.session.completed event")
        """Triggered when user completes a new subscription checkout."""
        session = event_data_obj.get("data", {}).get("object", {})

        # Extract details from event
        user_id = session.get("client_reference_id")  # you set this to the Django user id
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        email = session.get("customer_details", {}).get("email")
        name = session.get("customer_details", {}).get("name")

        if not user_id or not customer_id or not subscription_id:
            return Response({"error": "Missing required fields"}, status=400)

        # Get the user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Check if subscription already exists
        sub, created = StripeSubscription.objects.get_or_create(
            subscription_id=subscription_id,
            defaults={
                "user": user,
                "customer_id": customer_id,
                "product_name": "Ad free",
                "start_date": timezone.now().date(),
            },
        )

        if not created:
            # Update existing record if re-subscribed
            sub.user = user
            sub.customer_id = customer_id
            sub.start_date = timezone.now().date()
            sub.save(update_fields=["user", "customer_id", "start_date"])

        return Response({"success": True, "created": created})
    
    def handle_invoice_payment_succeeded(self, event_data_obj):
        """Triggered on renewal payments or initial invoices."""
        invoice = event_data_obj.get("data", {}).get("object", {})
        customer_id = invoice.get("customer")

        if not customer_id:
            return Response({"error": "Missing customer_id"}, status=400)

        stripe_sub = StripeSubscription.objects.filter(customer_id=customer_id).first()
        if not stripe_sub or not stripe_sub.user:
            return Response({"error": "No linked user"}, status=404)

        user = stripe_sub.user

        # Get the invoice’s first line item
        line_items = invoice.get("lines", {}).get("data", [])
        if not line_items:
            return Response({"error": "No line items"}, status=400)

        line = line_items[0]
        period = line.get("period", {})
        period_end = period.get("end")

        if not period_end:
            return Response({"error": "Missing period end"}, status=400)

        # ✅ Correct, working conversion:
        ad_free_until = datetime.datetime.fromtimestamp(period_end, tz=datetime.timezone.utc)

        # Only extend forward
        if not user.ad_free_until or ad_free_until > user.ad_free_until:
            user.ad_free_until = ad_free_until
            user.save(update_fields=["ad_free_until"])

        return Response({"success": True})

    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET,
                api_key=settings.STRIPE_SECRET_KEY
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            return Response({}, status=400)

        event_type = event["type"]

        # Handle only relevant events
        if event_type == "invoice.payment_succeeded":
            return self.handle_invoice_payment_succeeded(event)
        elif event_type == "checkout.session.completed":
            return self.handle_checkout_session_completed(event)

        return Response({}, status=200)
    
@api_view(["POST"])
def create_checkout_session(request):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        user_id = request.user.id
        product_type = request.data.get("product_type")  # 'monthly', 'yearly', or 'custom'
        months = int(request.data.get("months", 1))      # for 'custom' product type

        print('Creating checkout session for user:', user_id, 'product_type:', product_type, 'months:', months)

        # Pick the correct price ID from your Stripe config
        if product_type == "monthly":
            price_id = settings.STRIPE_MONTHLY_PRICE_ID
            quantity = 1
        elif product_type == "yearly":
            price_id = settings.STRIPE_YEARLY_PRICE_ID
            quantity = 1
        elif product_type == "custom":
            price_id = settings.STRIPE_CUSTOM_PRICE_ID
            quantity = months
        else:
            return Response({"error": "Invalid product type"}, status=status.HTTP_400_BAD_REQUEST)

        # URLs required by Stripe
        success_url = request.build_absolute_uri('/u/subscribe/success/')
        cancel_url = request.build_absolute_uri('/u/subscribe/cancel/')

        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[{"price": price_id, "quantity": quantity}],
            mode="subscription",
            client_reference_id=str(user_id),
            allow_promotion_codes=True,
            payment_method_types=["card"],
        )

        return redirect(checkout_session.url)

    except Exception as e:
        logger.exception("Unable to create stripe checkout session")
        return Response(
            {"error": f"Unable to create checkout session: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST
        )

from io import BytesIO
from django.core.files.base import ContentFile
from PIL import Image

@login_required
def account_settings(request):
    user = request.user

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        discord_username = request.POST.get('discord_username', '').strip()
        reg_background = request.POST.get('reg_background') == 'on'
        pfp = request.FILES.get('pfp')
        banner = request.FILES.get('banner')

        # Basic required field check
        if not username or not email:
            messages.error(request, "Username and email are required.")
            return redirect('account_settings')

        # Username validation
        if not re.match(r'^[\w.@+-]+$', username):
            messages.error(request, "Enter a valid username. This value may contain only letters, numbers, and @/./+/-/_ characters.")
            return redirect('account_settings')

        # Update user fields
        user.username = username
        user.email = email
        user.discord_username = request.POST.get('discord_username', '').strip()
        user.reg_background = reg_background

        # Image compression function
        def compress_image(uploaded_file, max_size=1600, quality=80):
            try:
                img = Image.open(uploaded_file)
                img = img.convert('RGB')

                width, height = img.size
                if width > max_size:
                    height = int(height * max_size / width)
                    width = max_size
                    img = img.resize((width, height), Image.Resampling.LANCZOS)

                output_io = BytesIO()
                img.save(output_io, format='WEBP', quality=quality)
                output_io.seek(0)
                return ContentFile(output_io.read(), name=f'{uploaded_file.name.rsplit(".",1)[0]}.webp')
            except Exception as e:
                print("Image compression error:", e)
                return uploaded_file

        if pfp:
            compressed_pfp = compress_image(pfp, max_size=300, quality=80)
            user.pfp.save(compressed_pfp.name, compressed_pfp, save=False)

        if banner:
            compressed_banner = compress_image(banner, max_size=1600, quality=80)
            user.banner.save(compressed_banner.name, compressed_banner, save=False)

        user.save()
        messages.success(request, "Account settings updated successfully.")
        return redirect('user_profile', username=user.username)
    else:
        form = AccountSettingsForm(instance=user)

    breadcrumbs = [
        {'name': 'Home', 'url': '/'},
        {'name': 'Account Settings', 'url': reverse('account_settings')},
    ]

    context = {
        'form': form,
    }
    return render(request, 'account_settings.html', {'breadcrumbs': breadcrumbs, **context})

@login_required
def delete_account(request):
    if request.method == 'POST':
        user = request.user
        logout(request)  # Ends the session before deleting
        user.delete()    # Deletes the user from the DB
        return redirect('/')
    
    breadcrumbs = [
        {'name': 'Home', 'url': '/'},
        {'name': 'Account Settings', 'url': reverse('account_settings')},
    ]

    return render(request, 'delete_account.html', {'user': request.user, 'breadcrumbs': breadcrumbs})

@login_required
def ticketer_code(request):
    user = request.user

    if request.method == 'POST':
        random_code = request.POST.get('ticketer_code', '').strip()

        user.ticketer_code = random_code
        user.save()

        return render(request, 'ticketer_code.html', {'user': user})

    if user.ticketer_code is None:
        random_code = randint(100000, 999999)  # Generate a random 6-digit code

        user.ticketer_code = random_code
        user.save()

    breadcrumbs = [
        {'name': 'Home', 'url': '/'},
        {'name': 'Account Settings', 'url': reverse('account_settings')},
    ]

    return render(request, 'ticketer_code.html', {'user': user, 'breadcrumbs': breadcrumbs})

@login_required
def user_liveries(request, username):
    user = get_object_or_404(CustomUser, username=username)

    liveries = liverie.objects.filter(added_by=user).order_by('-pk')

    mbt_perms = []
    if request.user.is_authenticated and request.user.mbt_team:
        mbt_perms = list(request.user.mbt_team.permissions.values_list('name', flat=True))


    breadcrumbs = [
        {'name': 'Home', 'url': '/'},
        {'name': 'Account Settings', 'url': reverse('account_settings')},
        {'name': 'My Liveries', 'url': reverse('user_liveries', kwargs={'username': user.username})},
    ]

    context = {
        'mbt_perms': mbt_perms,
        'username': username,
        'liveries': liveries,
        'breadcrumbs': breadcrumbs,
    }

    return render(request, 'user_liveries.html', context)

@csrf_exempt
def give_badge(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    import json
    try:
        data = json.loads(request.body)
        session_key = data.get("session_key")
        give_to_username = data.get("user")
        badge_name = data.get("badge")
        give = data.get("give", True)

        give_to_user = CustomUser.objects.filter(username=give_to_username).first()
        if not give_to_user:
            return JsonResponse({"error": "User not found"}, status=404)

        badge_to_give = badge.objects.filter(badge_name=badge_name).first()
        if not badge_to_give:
            return JsonResponse({"error": "Badge not found"}, status=404)
        
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not session_key:
        return JsonResponse({"error": "Missing session_key"}, status=401)

    # validate session
    try:
        user_key = UserKeys.objects.select_related("user").get(session_key=session_key)
        user = user_key.user

        if not user.is_superuser:
            return JsonResponse({"error": "Permission denied"}, status=403)
    except UserKeys.DoesNotExist:
        return JsonResponse({"error": "Invalid session key"}, status=401)

    if not give:
        give_to_user.badges.remove(badge_to_give)
        give_to_user.save()
        return JsonResponse({"success": "Badge removed successfully"}, status=200)

    give_to_user.badges.add(badge_to_give)
    give_to_user.save()

    return JsonResponse({"success": "Badge given successfully"}, status=200)

@csrf_exempt
def get_all_available_badges(request):
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    badges = badge.objects.all().values("badge_name").order_by("badge_name")
    return JsonResponse({"badges": list(badges)}, status=200)