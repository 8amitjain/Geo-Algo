from django.contrib import admin
from .models import *


class UserLogAdmin(admin.ModelAdmin):
    search_fields = (
        "user__email",
    )


admin.site.register(User)
admin.site.register(UserLog, UserLogAdmin)
