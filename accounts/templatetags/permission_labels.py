from django import template

from accounts.permission_labels import action_label, app_label, model_label

register = template.Library()


@register.filter
def permission_app_label(content_type):
    return app_label(content_type)


@register.filter
def permission_model_label(content_type):
    return model_label(content_type)


@register.filter
def permission_action_label(permission):
    return action_label(permission)
