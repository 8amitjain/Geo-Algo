from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for Django using email instead of a username for authentication.
    Includes basic fields like email, name, and flags for active status, verification, and staff status.
    """
    email = models.EmailField(unique=True, max_length=320, help_text='Provide an email for registration')
    name = models.CharField(max_length=70, null=True, blank=True, help_text='Full name of the user, optional.')

    dhan_access_token = models.TextField(null=True, blank=True, help_text='Dhan Access Token')
    dhan_client_id = models.CharField(max_length=200, null=True, blank=True, help_text='Dhan Client ID')
    dhan_access_token_expiry = models.DateField(null=True, blank=True, help_text='Dhan Access Token expiry date')

    RISK_CHOICES = [
        (500, '₹500'),
        (1000, '₹1,000'),
        (2000, '₹2,000'),
        (5000, '₹5,000'),
    ]

    risk_per_trade = models.IntegerField(
        choices=RISK_CHOICES,
        default=500,
        help_text='Maximum capital risk per trade. Used to calculate position size.'
    )

    trading_enabled = models.BooleanField(default=False, help_text='Trade using this account.')
    date_joined = models.DateTimeField(auto_now_add=True, help_text='The date and time this account was created.')
    is_active = models.BooleanField(default=False, help_text='Flag to indicate if the user account is active.')
    is_verified = models.BooleanField(default=False,
                                      help_text='Flag to indicate if the user account has been verified.')
    is_staff = models.BooleanField(default=False, help_text='Flag to indicate if the user can access the admin site.')

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        """
        Returns the email address of the user.
        """
        return self.email


class UserLog(models.Model):
    """
    Logs user actions within the application, recording the associated user, action performed, and the IP address from which the action was taken.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text='The user who performed the action.')
    action = models.CharField(max_length=255, help_text='Description of the action performed.')
    ip_address = models.GenericIPAddressField(null=True, blank=True,
                                              help_text='IP address of the user at the time of the action.')
    timestamp = models.DateTimeField(auto_now_add=True, help_text='The exact date and time when the action was logged.')

    def __str__(self):
        """
        Returns a string representation of the UserLog, including the user's email, action, and timestamp of the action.
        """
        return f"{self.user.email} - {self.action} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
