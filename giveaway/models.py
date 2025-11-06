from django.db import models
from main.models import CustomUser as User

# Create your models here.
class Prize(models.Model):
    name = models.CharField(max_length=100)
    tier = models.IntegerField(default=1)
    description = models.TextField()
    image = models.ImageField(upload_to='giveaway_prizes/', blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return self.name
    
class Entry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    prize = models.ForeignKey(Prize, on_delete=models.CASCADE)
    entered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Entry by {self.user.username} at {self.entered_at}"
    
class Winner(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    prize = models.ForeignKey(Prize, on_delete=models.CASCADE)
    won_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} won {self.prize.name}"