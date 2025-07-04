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
