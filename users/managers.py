from django.contrib.auth.base_user import BaseUserManager
from django.core.mail import send_mail
from django.conf import settings


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Creates and saves a User with the given username and password.
        """
        if not email:
            raise ValueError('Users must have an email address')
        # username = self.normalize_email(username)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        send_mail(
            'New User Created',
            'A new user has been created with email: {}'.format(user.email),
            settings.EMAIL_HOST_USER,
            ['8amitjain@gmail.com'],  # Admins email
            fail_silently=False,
        )
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)
