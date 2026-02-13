from django.shortcuts import render, redirect, get_object_or_404
from .models import Prize, Winner, Entry
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from main.models import CustomUser as User
from django.db.models import Count
import random

# Create your views here.
def giveaway_home(request):
    prizes = Prize.objects.annotate(winner_count=Count('winner')).order_by('tier')
    
    entered_prize_ids = set()
    if request.user.is_authenticated:
        entered_prize_ids = set(
            Entry.objects.filter(user=request.user).values_list('prize_id', flat=True)
        )
    
    return render(request, 'giveaway/home.html', {
        'prizes': prizes,
        'entered_prize_ids': entered_prize_ids,
    })


@login_required
def enter_giveaway(request, prize_id):
    prize = get_object_or_404(Prize, id=prize_id)

    # Prevent entering more times than quantity (optional)
    if Entry.objects.filter(user=request.user, prize=prize).exists():
        messages.error(request, "You have already entered for this prize.")
        return redirect('giveaway_home')

    Entry.objects.create(user=request.user, prize=prize)
    messages.success(request, f"You have successfully entered for: {prize.name}")

    return redirect('giveaway_home')

@login_required
def draw_winner(request):
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to access this page.")
        return redirect('giveaway_home')

    prizes = Prize.objects.annotate(winner_count=Count('winner')).order_by('tier')
    selected_prize = None
    winners = []
    remaining = None

    for p in prizes:
        p.remaining = p.quantity - p.winner_count

    if request.method == "POST":
        prize_id = request.POST.get("prize_id")
        selected_prize = get_object_or_404(Prize, id=prize_id)

        winners = Winner.objects.filter(prize=selected_prize).select_related('user', 'prize')
        remaining = selected_prize.quantity - winners.count()

        if remaining <= 0:
            messages.error(request, f"All winners have already been drawn for {selected_prize.name}.")
        else:
            entries = Entry.objects.filter(prize=selected_prize)

            if not entries.exists():
                messages.error(request, "No entries for this prize yet.")
            else:

                # ✅ NEW: Exclude *anyone who has already won ANY prize*
                global_winners = Winner.objects.values_list('user_id', flat=True)
                eligible_entries = entries.exclude(user_id__in=global_winners)

                if not eligible_entries.exists():
                    messages.error(request, "No eligible users left who haven't won something already.")
                else:
                    winner_entry = random.choice(eligible_entries)
                    Winner.objects.create(user=winner_entry.user, prize=selected_prize)
                    messages.success(request, f"🎉 {winner_entry.user.username} has won {selected_prize.name}!")

        winners = Winner.objects.filter(prize=selected_prize).select_related('user', 'prize')
        remaining = selected_prize.quantity - winners.count()

    # ✅ Still show full winner list
    all_winners = Winner.objects.select_related('user', 'prize').order_by('-won_at')

    return render(request, 'giveaway/draw_winner.html', {
        'prizes': prizes,
        'selected_prize': selected_prize,
        'winners': winners,
        'remaining': remaining,
        'all_winners': all_winners,
    })
