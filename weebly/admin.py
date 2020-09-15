from django.contrib import admin
from .models import *


class WeeblyStoreProductOptionInline(admin.TabularInline):
    model = WeeblyStoreProductOption


class WeeblyStoreProductAdmin(ModelAdmin, SiteDomainMixin):
    list_display = ['pk', 'product_id', 'site_domain', 'name', 'url_linked']
    search_fields = ['product_id', 'name', 'url', 'site__domain']
    readonly_fields = ['site', 'site_domain']
    inlines = [WeeblyStoreProductOptionInline]

    @domain_decorator(title="url", admin_order_field='url')
    def url_linked(self, obj): return obj.url


admin.site.register(WeeblyUser, WeeblyUser.Admin)
admin.site.register(WeeblySite, WeeblySite.Admin)
admin.site.register(WeeblyAuth, WeeblyAuth.Admin)
admin.site.register(WeeblyPaymentNotification, WeeblyPaymentNotification.Admin)
admin.site.register(WeeblyPage, WeeblyPage.Admin)
admin.site.register(WeeblyBlog, WeeblyBlog.Admin)
admin.site.register(WeeblyBlogPost, WeeblyBlogPost.Admin)
admin.site.register(WeeblyStoreCategory, WeeblyStoreCategory.Admin)
admin.site.register(WeeblyStoreProduct, WeeblyStoreProductAdmin)

