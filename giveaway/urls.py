from django.urls import path
from .views import *

urlpatterns = [
    path('', giveaway_home, name='giveaway_home'),
    path('enter/<int:prize_id>/', enter_giveaway, name='enter_giveaway'),
    path('draw/', draw_winner, name='draw_winner'),
]
