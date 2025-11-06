from django.contrib import admin
from .models import Prize, Entry, Winner
# Register your models here.

@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'quantity')
    search_fields = ('name', 'description')

@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'prize', 'entered_at')
    search_fields = ('user__username', 'prize__name')


@admin.register(Winner)
class WinnerAdmin(admin.ModelAdmin):
    list_display = ('user', 'prize', 'won_at')
    search_fields = ('user__username', 'prize__name')