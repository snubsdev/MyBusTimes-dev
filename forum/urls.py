from django.urls import path
from . import views

urlpatterns = [
    path('', views.forum_list, name='forum_list'),
    path('thread/<int:thread_id>/', views.thread_detail, name='thread_detail'),
    path('post/<int:post_id>/edit/', views.post_edit, name='post_edit'),
    path('post/<int:post_id>/delete/', views.post_delete, name='post_delete'),
    path('thread/new/', views.new_thread, name='new_thread'),
    path('banned/', views.forum_banned, name='forum_banned'),
    path("<str:forum_name>/", views.thread_list, name="thread_list"),
]