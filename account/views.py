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
from main.models import CustomUser, UserKeys, badge, StripeSubscription, ActiveSubscription
from a.models import AffiliateLink, Link
from main.models import featureToggle
import requests

logger = logging.getLogger(__name__)
User = get_user_model()
stripe.api_key = settings.STRIPE_SECRET_KEY

debug = settings.DEBUG

# Helpers for subscription handling
def _price_catalog():
    """Return a map of Stripe price IDs to plan metadata."""
    catalog = {
        settings.STRIPE_BASIC_MONTHLY_PRICE_ID: {"months": 1, "plan": "basic", "mode": "subscription"},
        settings.STRIPE_BASIC_YEARLY_PRICE_ID: {"months": 12, "plan": "basic", "mode": "subscription"},
        settings.STRIPE_BASIC_ONE_OFF_PRICE_ID: {"months": 1, "plan": "basic", "mode": "payment"},
        settings.STRIPE_PRO_MONTHLY_PRICE_ID: {"months": 1, "plan": "pro", "mode": "subscription"},
        settings.STRIPE_PRO_YEARLY_PRICE_ID: {"months": 12, "plan": "pro", "mode": "subscription"},
        settings.STRIPE_PRO_ONE_OFF_PRICE_ID: {"months": 1, "plan": "pro", "mode": "payment"},
        # Legacy IDs for backward compatibility
        settings.STRIPE_MONTHLY_PRICE_ID: {"months": 1, "plan": "basic", "mode": "subscription"},
        settings.STRIPE_YEARLY_PRICE_ID: {"months": 12, "plan": "basic", "mode": "subscription"},
        settings.STRIPE_CUSTOM_PRICE_ID: {"months": 1, "plan": "basic", "mode": "subscription"},
    }
    # Drop None values to avoid key collisions
    return {pid: meta for pid, meta in catalog.items() if pid}


def _extend_ad_free_until(user, months):
    """Calculate new ad free expiry using legacy month-adding logic."""
    if months <= 0:
        return user.ad_free_until
    base = user.ad_free_until if user.ad_free_until and user.ad_free_until > timezone.now() else timezone.now()
    return base + relativedelta(months=months)


def _apply_subscription_benefits(user, months, plan_level):
    """Extend ad-free period and set plan level if provided."""
    new_until = _extend_ad_free_until(user, months)
    update_fields = []

    if new_until and (not user.ad_free_until or new_until > user.ad_free_until):
        user.ad_free_until = new_until
        update_fields.append("ad_free_until")

    if plan_level and plan_level in dict(CustomUser.PLAN_CHOICES):
        if user.sub_plan != plan_level:
            user.sub_plan = plan_level
            update_fields.append("sub_plan")

    if update_fields:
        user.save(update_fields=update_fields)

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
    feature = featureToggle.objects.get(name="register")
    if not feature.enabled:
        return render(request, 'feature_disabled.html', {'feature_name': "register"}, status=200)

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

            # email and username validation
            if form.cleaned_data['email'] and CustomUser.objects.filter(email=form.cleaned_data['email']).exists():
                form.add_error('email', 'Email address is already in use.')

            if form.cleaned_data['username'] and CustomUser.objects.filter(username=form.cleaned_data['username']).exists():
                form.add_error('username', 'Username is already taken.')

            if ' ' in form.cleaned_data.get('username', ''):
                form.add_error('username', 'Username cannot contain spaces')

            # 🔥 NEW IMPORTANT CHECK — DO NOT SAVE IF ERRORS WERE ADDED
            if form.errors:
                return render(request, 'register.html', {'form': form})

            # Continue only if validation success
            if validation['success']:
                user = form.save()

                # invite cookie support
                invite_id = request.COOKIES.get("invite_id")
                if invite_id:
                    try:
                        link = AffiliateLink.objects.get(id=invite_id)
                        link.signups_from_clicks += 1
                        link.save()
                    except AffiliateLink.DoesNotExist:
                        pass

                # login new user
                user.backend = settings.AUTHENTICATION_BACKENDS[0]
                login(request, user)

                response = redirect(f'/u/{user.username}')
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

    groups = group.objects.filter(group_owner=profile_user).order_by('group_name')

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

    sub_status = {}

    # Filter to only currently active subscriptions
    user_active_subs = ActiveSubscription.objects.filter(
        user=profile_user,
        end_date__gt=timezone.now()
    ).order_by('-end_date')

    sub_count = user_active_subs.count()
    
    if sub_count > 1:
        counter = 0
        for sub in user_active_subs:
            counter += 1
            sub_status[f"sub_{counter}"] = {
                'plan': sub.plan,
                'until': sub.end_date.strftime("%Y-%m-%d"),
                'is_trial': sub.is_trial
            }
    elif sub_count == 1:
        sub = user_active_subs.first()
        sub_status["sub_1"] = {
            'plan': sub.plan,
            'until': sub.end_date.strftime("%Y-%m-%d"),
            'is_trial': sub.is_trial
        }
    else:
        sub_status["sub_1"] = {'plan': 'free', 'until': 'N/A', 'is_trial': False}

    context = {
        'sub_status': sub_status,
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

def calculate_sub_class(user):
    """Return current subscription tier string based on Stripe subscription.

    - Staff users fall back to basic_monthly if no valid subscription is found.
    - Looks up the latest StripeSubscription for the user, fetches the live
      subscription from Stripe, and maps the price to a plan using _price_catalog.
    - Falls back to the user's stored sub_plan or "free" if unavailable.
    """

    # Find the latest subscription record for this user
    sub_record = (
        StripeSubscription.objects.filter(user=user)
        .order_by("-id")
        .first()
    )

    if not sub_record or not sub_record.subscription_id:
        return user.sub_plan or "free"

    try:
        stripe_sub = stripe.Subscription.retrieve(sub_record.subscription_id)
    except Exception as exc:  # Stripe errors / network
        print("[calculate_sub_class] Stripe retrieve failed:", exc)
        return user.sub_plan or "free"

    # Extract price id from first item
    items = stripe_sub.get("items", {}).get("data", []) if stripe_sub else []
    if not items:
        return user.sub_plan or "free"

    price_id = items[0].get("price", {}).get("id")
    price_map = _price_catalog()
    if price_id and price_id in price_map:
        plan = price_map[price_id]["plan"]
        interval_months = price_map[price_id].get("months", 1)
        # Build a simple tier label
        if interval_months >= 12:
            return f"{plan}_yearly"
        if interval_months >= 1:
            return f"{plan}_monthly"
        return plan

    if user.is_staff:
        return "basic_monthly"


    return user.sub_plan or "free"

@login_required
def subscribe_ad_free(request):
    today = timezone.now()
    current_sub_count = CustomUser.objects.filter(
        ad_free_until__gt=today,
        is_staff=False
    ).count()

    had_pro_trial = request.user.had_pro_trial

    current_sub = calculate_sub_class(request.user)

    return render(request, 'subscribe.html', {'had_pro_trial': had_pro_trial, 'current_sub': current_sub, 'month_options': range(1, 13), 'current_sub_count': current_sub_count})

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

    def log(self, *args):
        print("[StripeWebhook DEBUG]", *args)

    def post(self, request):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        print("🔔 Received webhook POST")
        print("Payload (truncated):", payload[:300])

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except Exception as e:
            print("❌ Webhook verification failed:", str(e))
            return Response(status=400)

        event_type = event.get("type")
        data_obj = event.get("data", {}).get("object", {})

        print("📌 Event type:", event_type)

        try:
            if event_type == "checkout.session.completed":
                return self.handle_checkout_session_completed(data_obj)
            elif event_type == "invoice.payment_succeeded":
                return self.handle_invoice_payment_succeeded(data_obj)
            else:
                print("⚠ Unhandled event type:", event_type)
                return Response(status=200)

        except Exception as e:
            print("❗ Handler exception:", str(e))
            import traceback
            traceback.print_exc()
            return Response(status=500)

    def handle_checkout_session_completed(self, session):
        print("👉 Handling checkout.session.completed")
        print("Session metadata:", session.get("metadata"))

        user_id = session.get("client_reference_id")
        subscription_id = session.get("subscription")
        customer_id = session.get("customer")

        if not user_id:
            print("❌ Missing client_reference_id in session")
            return Response(status=400)

        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            print("❌ User not found:", user_id)
            return Response(status=404)

        # Ensure StripeSubscription record exists/updated
        if subscription_id:
            sub_defaults = {
                "user": user,
                "customer_id": customer_id,
                "product_name": "Ad free",
                "start_date": timezone.now().date(),
            }
            sub_obj, created = StripeSubscription.objects.update_or_create(
                subscription_id=subscription_id,
                defaults=sub_defaults,
            )
            if created:
                print("✔ Created StripeSubscription record")
            else:
                print("✔ Updated StripeSubscription record")

        # Save subscription ID
        if subscription_id:
            user.stripe_subscription_id = subscription_id
            print("✔ Stored stripe_subscription_id:", subscription_id)

        # If checkout session metadata has plan info, use it
        session_meta = session.get("metadata") or {}
        plan_level = session_meta.get("plan_level")
        months = session_meta.get("months")

        if plan_level:
            user.sub_plan = plan_level
            print("✔ Set plan from session metadata:", plan_level)

        if months:
            try:
                dur = int(months)
                user.ad_free_until = timezone.now() + datetime.timedelta(days=30*dur)
                print("✔ Set ad_free_until from session metadata:", user.ad_free_until)
            except Exception as e:
                print("⚠ Could not parse months metadata:", str(e))

        user.save(update_fields=["sub_plan", "ad_free_until", "stripe_subscription_id"])

        # Create ActiveSubscription record (works for both subscriptions and one-off payments)
        effective_plan = plan_level or user.sub_plan or "basic"
        if subscription_id:
            # For recurring subscriptions, use get_or_create with subscription_id
            ActiveSubscription.objects.get_or_create(
                stripe_subscription_id=subscription_id,
                defaults={
                    "user": user,
                    "start_date": timezone.now(),
                    "end_date": user.ad_free_until + timedelta(days=7), # grace period
                    "plan": effective_plan,
                    "is_trial": False,
                }
            )
            print("✔ Created ActiveSubscription record for subscription")
        elif plan_level and user.ad_free_until:
            # For one-off payments, create without subscription_id
            ActiveSubscription.objects.create(
                user=user,
                stripe_subscription_id=None,
                start_date=timezone.now(),
                end_date=user.ad_free_until + timedelta(days=7), # grace period
                plan=effective_plan,
                is_trial=False,
            )
            print("✔ Created ActiveSubscription record for one-off payment")

        print("✔ Completed checkout.session.completed")
        return Response(status=200)

    def handle_invoice_payment_succeeded(self, invoice):
        print("👉 Handling invoice.payment_succeeded")
        print("Invoice top-level metadata:", invoice.get("metadata"))

        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")

        # Find user
        user = None
        sub_obj = None
        if subscription_id:
            sub_obj = StripeSubscription.objects.filter(subscription_id=subscription_id).first()
            if sub_obj:
                user = sub_obj.user
                print("✔ Found user via subscription_id:", user.username)

        if not user and customer_id:
            sub_obj = StripeSubscription.objects.filter(customer_id=customer_id).order_by("-id").first()
            if sub_obj:
                user = sub_obj.user
                print("✔ Found user via customer_id:", user.username)

        if not user:
            print("❌ No linked user found for invoice")
            return Response(status=404)

        # Get first invoice line
        lines = invoice.get("lines", {}).get("data", [])
        if not lines:
            print("❌ No invoice lines found")
            return Response(status=400)

        first_line = lines[0]
        line_meta = first_line.get("metadata") or {}
        print("Line item metadata:", line_meta)

        # Extract billing period end
        period = first_line.get("period", {})
        period_end_ts = period.get("end")
        if not period_end_ts:
            print("❌ Missing period end on invoice line")
            return Response(status=400)

        ad_free_until = datetime.datetime.fromtimestamp(period_end_ts, tz=datetime.timezone.utc)
        print("✔ Calculated ad_free_until:", ad_free_until)
        if not user.ad_free_until or ad_free_until > user.ad_free_until:
            user.ad_free_until = ad_free_until

        # Extract plan from line item metadata
        plan_level = line_meta.get("plan_level")
        if plan_level:
            user.sub_plan = plan_level
            print("✔ Set user.sub_plan from line metadata:", plan_level)

        user.save(update_fields=["ad_free_until", "sub_plan"])
        print("✔ User updated:", user.username, user.sub_plan, user.ad_free_until)


        # Update or create subscription record
        if subscription_id:
            StripeSubscription.objects.update_or_create(
                subscription_id=subscription_id,
                defaults={"end_date": ad_free_until.date(), "user": user}
            )
            print("✔ Updated StripeSubscription end_date")

            # Create new ActiveSubscription record for this payment period
            ActiveSubscription.objects.get_or_create(
                user=user,
                stripe_subscription_id=subscription_id,
                start_date=timezone.now(),
                end_date=ad_free_until + timedelta(days=7), # grace period
                plan=plan_level or user.sub_plan or "basic",
                is_trial=False
            )
            print("✔ Created ActiveSubscription record for invoice payment")

        return Response(status=200)
    
@api_view(["POST"])
def create_checkout_session(request):
    stripe.api_key = settings.STRIPE_SECRET_KEY

    if request.data.get("product_type", "").endswith("_free_trial"):
        days = int(request.data.get("months", 7))
        product_type = request.data.get("product_type").replace("_free_trial", "")

        user = request.user
        current_ad_free = max(user.ad_free_until, timezone.now()) if user.ad_free_until else timezone.now()
        new_ad_free_until = current_ad_free + datetime.timedelta(days=days)

        user.sub_plan = product_type
        user.had_pro_trial = True
        user.ad_free_until = new_ad_free_until

        user.save(update_fields=["sub_plan", "had_pro_trial", "ad_free_until"])

        # Create ActiveSubscription record for the free trial
        ActiveSubscription.objects.create(
            user=user,
            stripe_subscription_id=None,
            start_date=timezone.now(),
            end_date=new_ad_free_until + timedelta(days=7), # grace period
            plan=product_type,
            is_trial=True
        )
        print("✔ Created ActiveSubscription for free trial")

        return redirect('/u/subscribe/success/')
    
    else:

        try:
            user_id = request.user.id
            product_type = request.data.get("product_type")
            try:
                months = int(request.data.get("months", 1))
            except (TypeError, ValueError):
                return Response({"error": "Invalid months value"}, status=status.HTTP_400_BAD_REQUEST)

            price_map = _price_catalog()
            price_id = None
            plan_level = None
            mode = "subscription"
            quantity = 1

            # Map product_type to price IDs (new and legacy)
            if product_type == "basic_monthly":
                price_id = settings.STRIPE_BASIC_MONTHLY_PRICE_ID
            elif product_type == "pro_monthly":
                price_id = settings.STRIPE_PRO_MONTHLY_PRICE_ID
                plan_level = "pro"
            elif product_type == "basic_yearly":
                price_id = settings.STRIPE_BASIC_YEARLY_PRICE_ID
                months = 12
            elif product_type == "pro_yearly":
                price_id = settings.STRIPE_PRO_YEARLY_PRICE_ID
                months = 12
                plan_level = "pro"
            elif product_type == "basic_one_off":
                price_id = settings.STRIPE_BASIC_ONE_OFF_PRICE_ID
                mode = "payment"
            elif product_type == "pro_one_off":
                price_id = settings.STRIPE_PRO_ONE_OFF_PRICE_ID
                mode = "payment"
                plan_level = "pro"
            elif product_type == "monthly":  # legacy
                price_id = settings.STRIPE_MONTHLY_PRICE_ID
            elif product_type == "yearly":  # legacy
                price_id = settings.STRIPE_YEARLY_PRICE_ID
                months = 12
            elif product_type == "custom":  # legacy custom quantity
                price_id = settings.STRIPE_CUSTOM_PRICE_ID
                quantity = months

            if price_id and price_id in price_map:
                plan_level = plan_level or price_map[price_id]["plan"]
                mode = price_map[price_id]["mode"]
            
            if not price_id:
                return Response({"error": "Invalid product type"}, status=status.HTTP_400_BAD_REQUEST)

            print("[checkout_session] user", user_id, "product_type", product_type, "price_id", price_id, "months", months, "plan", plan_level, "mode", mode, "quantity", quantity)

            # URLs required by Stripe
            success_url = request.build_absolute_uri('/u/subscribe/success/')
            cancel_url = request.build_absolute_uri('/u/subscribe/cancel/')

            session_params = {
                "success_url": success_url,
                "cancel_url": cancel_url,
                "line_items": [{"price": price_id, "quantity": quantity}],
                "mode": mode,
                "client_reference_id": str(user_id),
                "allow_promotion_codes": True,
                "payment_method_types": ["card"],
                "metadata": {
                    "user_id": str(user_id),
                    "product_type": product_type,
                    "months": str(months),
                    "plan_level": plan_level or "basic",
                },
            }

            # Persist plan and months on the subscription itself so invoice events can read them
            if mode == "subscription":
                session_params["subscription_data"] = {
                    "metadata": {
                        "months": str(months),
                        "plan_level": plan_level or "basic",
                    }
                }

            checkout_session = stripe.checkout.Session.create(**session_params)

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